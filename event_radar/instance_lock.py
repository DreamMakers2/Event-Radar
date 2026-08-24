from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from pathlib import Path
from typing import TextIO

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from event_radar.config import Settings
from event_radar.utils import utc_now


class EventRadarInstanceRunningError(RuntimeError):
    pass


class EventRadarInstanceLock:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = self._build_lock_path(settings)
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        handle.seek(0)
        try:
            self._lock_handle(handle)
        except (BlockingIOError, OSError) as exc:
            details = self._read_details(handle)
            handle.close()
            detail_text = self._format_details(details)
            raise EventRadarInstanceRunningError(
                f"event_radar_instance_running: {detail_text}"
            ) from exc

        handle.seek(0)
        handle.truncate()
        json.dump(
            {
                "pid": os.getpid(),
                "app_host": self.settings.app_host,
                "app_port": self.settings.app_port,
                "database_path": str(self.settings.effective_database_path),
                "started_at": utc_now().isoformat(),
            },
            handle,
        )
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return

        try:
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._unlock_handle(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def _build_lock_path(self, settings: Settings) -> Path:
        database_path = settings.effective_database_path.resolve()
        database_name = re.sub(r"[^A-Za-z0-9._-]+", "_", database_path.stem)
        database_fingerprint = sha256(str(database_path).encode("utf-8")).hexdigest()[:12]
        return settings.effective_database_path.parent / f"event_radar.{database_name}.{database_fingerprint}.lock"

    def _read_details(self, handle: TextIO) -> dict[str, str]:
        handle.seek(0)
        raw = handle.read().strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return {str(key): str(value) for key, value in payload.items()}

    def _format_details(self, details: dict[str, str]) -> str:
        if not details:
            return f"lock_path={self.path}"
        pid = details.get("pid")
        host = details.get("app_host")
        port = details.get("app_port")
        database_path = details.get("database_path")
        parts = [
            f"pid={pid}" if pid else None,
            f"host={host}" if host else None,
            f"port={port}" if port else None,
            f"database_path={database_path}" if database_path else None,
        ]
        formatted = " ".join(part for part in parts if part)
        return formatted or f"lock_path={self.path}"

    def _lock_handle(self, handle: TextIO) -> None:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_handle(self, handle: TextIO) -> None:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
