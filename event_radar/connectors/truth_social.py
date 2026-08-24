from __future__ import annotations

import asyncio
import http.cookiejar
import json
import random
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from event_radar.config import Settings
from event_radar.connectors.base import BaseConnector, PostHandler
from event_radar.connectors.truth_social_browser import (
    TruthSocialBrowserClient,
    TruthSocialBrowserError,
    TruthSocialBrowserRateLimitError,
)
from event_radar.db import Repository
from event_radar.models import AccountConfig, CanonicalPost, SourcePlatform
from event_radar.utils import clean_html_text, parse_datetime, read_json_file, split_cookie_header, utc_now


class TruthSocialRateLimitError(RuntimeError):
    def __init__(self, *, retry_seconds: float, retry_after: str | None = None) -> None:
        super().__init__("truth_social_rate_limited")
        self.retry_seconds = retry_seconds
        self.retry_after = retry_after


class TruthSocialConnector(BaseConnector):
    _RATE_LIMIT_FALLBACK_SECONDS = 60.0
    _RATE_LIMIT_MIN_SECONDS = 15.0
    _RATE_LIMIT_MAX_SECONDS = 900.0
    _BROWSER_BASE_POLL_SECONDS = 45.0

    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository,
        on_post: PostHandler,
        on_activity=None,
    ) -> None:
        super().__init__(settings=settings, repository=repository, on_post=on_post, on_activity=on_activity)
        self._browser_client: TruthSocialBrowserClient | None = None
        self._prefer_browser_fetch = False
        self._browser_fallback_announced = False
        self._rate_limit_streak = 0

    @property
    def name(self) -> str:
        return "truth_social"

    @property
    def poll_sleep_seconds(self) -> float:
        return self.settings.truth_social_poll_seconds

    async def close(self) -> None:
        if self._browser_client is not None:
            await self._browser_client.close()
            self._browser_client = None

    async def run(self, stop_event: asyncio.Event) -> None:
        accounts = await self.repository.list_accounts(active_only=True, source=SourcePlatform.TRUTH_SOCIAL)
        enabled = bool(accounts)
        auth_configured = bool(self.settings.truth_social_cookie or self.settings.truth_social_cookie_file)
        self.mark_running(enabled=enabled, auth_configured=auth_configured, detail="starting")
        if not enabled or not auth_configured:
            if not accounts:
                self.status.detail = "no_active_accounts"
            else:
                self.status.detail = "missing_truth_social_session"
            await self.emit_activity("warning", "Truth Social connector inactive", self.status.detail or "inactive")
            await stop_event.wait()
            return
        await self.emit_activity("info", "Truth Social connector starting", "Starting session-backed account polling.")
        while not stop_event.is_set():
            sleep_for = self._sleep_seconds_after_success()
            try:
                await self.poll_once()
                self._rate_limit_streak = 0
                self.mark_success(detail=self._steady_state_detail(), when=utc_now())
            except TruthSocialRateLimitError as exc:
                self._rate_limit_streak += 1
                sleep_for = self._sleep_seconds_after_rate_limit(exc.retry_seconds)
                self._mark_rate_limited(sleep_for)
                await self.emit_activity(
                    "warning",
                    "Truth Social rate limited",
                    f"Truth Social hit a rate limit; retrying in {int(sleep_for)} seconds.",
                    metadata={"retry_seconds": sleep_for, "retry_after": exc.retry_after},
                )
            except Exception as exc:  # noqa: BLE001
                self.mark_error(f"poll_failed: {exc}")
                await self.emit_activity("error", "Truth Social polling failed", str(exc))
            if await self.sleep_or_stop(stop_event, sleep_for):
                return

    async def poll_once(self) -> None:
        accounts = await self.repository.list_accounts(active_only=True, source=SourcePlatform.TRUTH_SOCIAL)
        async with self._client() as client:
            for account in accounts:
                await self._poll_account(client, account)

    async def _poll_account(self, client: httpx.AsyncClient, account: AccountConfig) -> None:
        statuses: list[dict[str, Any]]
        source_account_id: str
        if self._prefer_browser_fetch:
            source_account_id, statuses = await self._poll_account_via_browser(account)
        else:
            try:
                source_account_id, statuses = await self._poll_account_via_http(client, account)
            except RuntimeError as exc:
                if str(exc) not in {"truth_social_lookup_forbidden", "truth_social_auth_forbidden"}:
                    raise
                await self._activate_browser_fallback(reason=str(exc))
                source_account_id, statuses = await self._poll_account_via_browser(account)
        checkpoint = await self.repository.get_checkpoint(self.name, account.id)
        last_seen = checkpoint.get("last_source_post_id") if checkpoint else None
        ordered = []
        for item in statuses:
            item_id = str(item["id"])
            if last_seen and item_id.isdigit() and last_seen.isdigit() and int(item_id) <= int(last_seen):
                continue
            ordered.append(item)
        for item in reversed(ordered):
            post = self.normalize_status_payload(item, account)
            await self.on_post(self.name, account, post)

    async def _poll_account_via_http(
        self,
        client: httpx.AsyncClient,
        account: AccountConfig,
    ) -> tuple[str, list[dict[str, Any]]]:
        source_account_id = account.source_account_id or await self._resolve_account_id(client, account)
        params = {"limit": 5, "exclude_replies": "false"}
        response = await client.get(f"/api/v1/accounts/{source_account_id}/statuses", params=params)
        if response.status_code == 403:
            raise RuntimeError("truth_social_auth_forbidden")
        if response.status_code == 429:
            raise self._rate_limit_error(response.headers.get("Retry-After"))
        response.raise_for_status()
        payload = response.json()
        return source_account_id, payload

    async def _poll_account_via_browser(self, account: AccountConfig) -> tuple[str, list[dict[str, Any]]]:
        try:
            payload = await self._browser().fetch_account_statuses(
                handle=account.handle,
                source_account_id=account.source_account_id,
                limit=5,
                exclude_replies=False,
            )
        except TruthSocialBrowserRateLimitError as exc:
            raise self._rate_limit_error(exc.retry_after) from exc
        except TruthSocialBrowserError as exc:
            raise RuntimeError(str(exc)) from exc
        account_payload = payload.get("account") or {}
        source_account_id = str(account_payload.get("id") or account.source_account_id or account.handle)
        source_url = account_payload.get("url")
        if source_account_id and source_account_id != account.source_account_id:
            await self.repository.resolve_account_identity(account.id, source_account_id, source_url)
        statuses = payload.get("statuses")
        if not isinstance(statuses, list):
            raise RuntimeError("truth_social_browser_invalid_statuses")
        return source_account_id, statuses

    async def _resolve_account_id(self, client: httpx.AsyncClient, account: AccountConfig) -> str:
        response = await client.get("/api/v1/accounts/lookup", params={"acct": account.handle})
        if response.status_code == 429:
            raise self._rate_limit_error(response.headers.get("Retry-After"))
        if response.status_code == 403:
            raise RuntimeError("truth_social_lookup_forbidden")
        response.raise_for_status()
        data = response.json()
        account_id = str(data["id"])
        await self.repository.resolve_account_identity(account.id, account_id, data.get("url"))
        return account_id

    def normalize_status_payload(self, item: dict[str, Any], account: AccountConfig) -> CanonicalPost:
        media_urls = [
            attachment.get("url") or attachment.get("preview_url")
            for attachment in item.get("media_attachments", [])
            if attachment.get("url") or attachment.get("preview_url")
        ]
        links = []
        if item.get("url"):
            links.append(item["url"])
        if card := item.get("card"):
            if card.get("url"):
                links.append(card["url"])
        text_parts = [clean_html_text(item.get("spoiler_text", "")), clean_html_text(item.get("content", ""))]
        text = " ".join(part for part in text_parts if part).strip()
        published_at = parse_datetime(item.get("created_at")) or utc_now()
        return CanonicalPost(
            source=SourcePlatform.TRUTH_SOCIAL,
            account_db_id=account.id,
            source_account_id=str(item.get("account", {}).get("id") or account.source_account_id or account.handle),
            display_name=account.display_name,
            handle=account.handle,
            source_post_id=str(item["id"]),
            canonical_url=item.get("url") or f"{self.settings.truth_social_base_url}/@{account.handle}/{item['id']}",
            text=text,
            links=links,
            media_urls=media_urls,
            is_reply=bool(item.get("in_reply_to_id")),
            is_repost=bool(item.get("reblog")),
            published_at=published_at,
            observed_at=utc_now(),
            raw_payload=item,
            collector_metadata={"connector": self.name},
        )

    def _cookie_mapping(self) -> dict[str, str]:
        if self.settings.truth_social_cookie:
            return split_cookie_header(self.settings.truth_social_cookie.get_secret_value())
        if not self.settings.truth_social_cookie_file:
            return {}
        path = Path(self.settings.truth_social_cookie_file)
        if not path.exists():
            return {}
        try:
            raw = read_json_file(path)
            if isinstance(raw, dict):
                return {str(key): str(value) for key, value in raw.items()}
            if isinstance(raw, list):
                return {str(item["name"]): str(item["value"]) for item in raw if "name" in item and "value" in item}
        except json.JSONDecodeError:
            pass
        jar = http.cookiejar.MozillaCookieJar()
        jar.load(str(path), ignore_discard=True, ignore_expires=True)
        return {cookie.name: cookie.value for cookie in jar}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.truth_social_base_url,
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": self.settings.truth_social_base_url,
            },
            cookies=self._cookie_mapping(),
        )

    def _browser(self) -> TruthSocialBrowserClient:
        if self._browser_client is None:
            self._browser_client = self._build_browser_client()
        return self._browser_client

    def _build_browser_client(self) -> TruthSocialBrowserClient:
        return TruthSocialBrowserClient(self.settings)

    async def _activate_browser_fallback(self, *, reason: str) -> None:
        self._prefer_browser_fetch = True
        self.status.detail = "browser_backed_polling"
        if self._browser_fallback_announced:
            return
        self._browser_fallback_announced = True
        await self.emit_activity(
            "warning",
            "Truth Social switched to browser mode",
            "Direct API requests were blocked on this host; continuing with browser-backed polling.",
            {"reason": reason},
        )

    def _steady_state_detail(self) -> str:
        if self._prefer_browser_fetch:
            return "browser_backed_polling"
        return "poll_ok"

    def _mark_rate_limited(self, retry_seconds: float) -> None:
        self.status.running = True
        self.status.last_error = None
        mode = "browser_" if self._prefer_browser_fetch else ""
        self.status.detail = f"{mode}rate_limited_retrying_in:{int(retry_seconds)}s"

    def _rate_limit_error(self, retry_after: str | None) -> TruthSocialRateLimitError:
        return TruthSocialRateLimitError(
            retry_seconds=self._retry_after_seconds(retry_after),
            retry_after=retry_after,
        )

    def _retry_after_seconds(self, retry_after: str | None) -> float:
        if retry_after:
            stripped = retry_after.strip()
            if stripped.isdigit():
                seconds = float(stripped)
                return max(self._RATE_LIMIT_MIN_SECONDS, min(seconds, self._RATE_LIMIT_MAX_SECONDS))
            try:
                parsed = parsedate_to_datetime(stripped)
                seconds = max((parsed - utc_now()).total_seconds(), self._RATE_LIMIT_MIN_SECONDS)
                return min(seconds, self._RATE_LIMIT_MAX_SECONDS)
            except (TypeError, ValueError, OverflowError):
                pass
        return self._RATE_LIMIT_FALLBACK_SECONDS

    def _sleep_seconds_after_success(self) -> float:
        base = self._base_poll_seconds()
        return base + random.uniform(0, 0.75)

    def _sleep_seconds_after_rate_limit(self, requested_retry_seconds: float) -> float:
        base = self._base_poll_seconds()
        streak_backoff = base * (2**self._rate_limit_streak)
        retry_seconds = max(requested_retry_seconds, streak_backoff)
        return min(retry_seconds, self._RATE_LIMIT_MAX_SECONDS)

    def _base_poll_seconds(self) -> float:
        configured = max(self.settings.truth_social_poll_seconds, self._RATE_LIMIT_MIN_SECONDS)
        if self._prefer_browser_fetch:
            return max(configured, self._BROWSER_BASE_POLL_SECONDS)
        return configured
