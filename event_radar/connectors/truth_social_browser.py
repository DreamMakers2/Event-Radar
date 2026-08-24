from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any

from event_radar.config import Settings


LOGGER = logging.getLogger(__name__)


class TruthSocialBrowserError(RuntimeError):
    """Raised when the browser-backed Truth Social worker cannot fulfill a request."""


class TruthSocialBrowserRateLimitError(TruthSocialBrowserError):
    def __init__(self, retry_after: str | None = None) -> None:
        super().__init__("truth_social_rate_limited")
        self.retry_after = retry_after


class TruthSocialBrowserClient:
    _STARTUP_TIMEOUT_SECONDS = 60.0
    _REQUEST_TIMEOUT_SECONDS = 45.0
    _SHUTDOWN_TIMEOUT_SECONDS = 10.0
    _STREAM_LIMIT_BYTES = 1_048_576

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._worker_path = Path(__file__).resolve().parents[2] / "scripts" / "truthsocial_browser_worker.mjs"

    async def fetch_account_statuses(
        self,
        *,
        handle: str,
        source_account_id: str | None,
        limit: int,
        exclude_replies: bool,
    ) -> dict[str, Any]:
        async with self._lock:
            await self._ensure_started()
            await self._send_request(
                {
                    "type": "fetch_statuses",
                    "handle": handle,
                    "sourceAccountId": source_account_id,
                    "limit": limit,
                    "excludeReplies": exclude_replies,
                }
            )
            response = await self._read_response(timeout=self._REQUEST_TIMEOUT_SECONDS)
            if response.get("ok") is True:
                result = response.get("result")
                if isinstance(result, dict):
                    return result
                raise TruthSocialBrowserError("truth_social_browser_invalid_result")
            if response.get("error") == "truth_social_rate_limited":
                raise TruthSocialBrowserRateLimitError(response.get("retryAfter"))
            raise TruthSocialBrowserError(str(response.get("error") or "truth_social_browser_request_failed"))

    async def close(self) -> None:
        async with self._lock:
            process = self._process
            if process is None:
                return
            try:
                if process.returncode is None and process.stdin is not None:
                    await self._send_request({"type": "shutdown"})
                    try:
                        await asyncio.wait_for(process.wait(), timeout=self._SHUTDOWN_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=self._SHUTDOWN_TIMEOUT_SECONDS)
            except ProcessLookupError:
                pass
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                if self._stderr_task is not None:
                    self._stderr_task.cancel()
                    await asyncio.gather(self._stderr_task, return_exceptions=True)
                self._stderr_task = None
                self._process = None

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        if not self._worker_path.exists():
            raise TruthSocialBrowserError("truth_social_browser_worker_missing")
        env = os.environ.copy()
        env["EVENT_RADAR_TRUTH_SOCIAL_BASE_URL"] = self.settings.truth_social_base_url
        if self.settings.truth_social_cookie_file is not None:
            env["EVENT_RADAR_TRUTH_SOCIAL_COOKIE_FILE"] = str(self.settings.truth_social_cookie_file)
        if self.settings.truth_social_cookie is not None:
            env["EVENT_RADAR_TRUTH_SOCIAL_COOKIE"] = self.settings.truth_social_cookie.get_secret_value()
        try:
            self._process = await asyncio.create_subprocess_exec(
                "node",
                str(self._worker_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=self._STREAM_LIMIT_BYTES,
            )
        except FileNotFoundError as exc:
            raise TruthSocialBrowserError("truth_social_browser_runtime_missing") from exc
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        response = await self._read_response(timeout=self._STARTUP_TIMEOUT_SECONDS)
        if response.get("type") != "ready":
            raise TruthSocialBrowserError(str(response.get("error") or "truth_social_browser_worker_failed_to_start"))

    async def _send_request(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise TruthSocialBrowserError("truth_social_browser_worker_stdin_closed")
        process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
        await process.stdin.drain()

    async def _read_response(self, *, timeout: float) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise TruthSocialBrowserError("truth_social_browser_worker_stdout_closed")
        try:
            raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TruthSocialBrowserError("truth_social_browser_request_timed_out") from exc
        except ValueError as exc:
            raise TruthSocialBrowserError("truth_social_browser_response_too_large") from exc
        if not raw_line:
            detail = self._stderr_summary()
            raise TruthSocialBrowserError(detail or "truth_social_browser_worker_exited")
        try:
            parsed = json.loads(raw_line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise TruthSocialBrowserError("truth_social_browser_invalid_json") from exc
        if not isinstance(parsed, dict):
            raise TruthSocialBrowserError("truth_social_browser_invalid_payload")
        return parsed

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            try:
                raw_line = await process.stderr.readline()
            except ValueError:
                self._stderr_tail.append("truth_social_browser_stderr_too_large")
                LOGGER.warning("truth_social browser worker: stderr output exceeded stream limit")
                return
            if not raw_line:
                return
            message = raw_line.decode("utf-8", errors="replace").strip()
            if not message:
                continue
            self._stderr_tail.append(message)
            LOGGER.warning("truth_social browser worker: %s", message)

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise TruthSocialBrowserError("truth_social_browser_worker_not_started")
        if self._process.returncode is not None:
            detail = self._stderr_summary()
            raise TruthSocialBrowserError(detail or f"truth_social_browser_worker_exited:{self._process.returncode}")
        return self._process

    def _stderr_summary(self) -> str:
        if not self._stderr_tail:
            return ""
        return "truth_social_browser_worker_failed:" + " | ".join(self._stderr_tail)
