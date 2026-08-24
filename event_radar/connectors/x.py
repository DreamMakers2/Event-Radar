from __future__ import annotations

import asyncio
import json
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from event_radar.config import Settings
from event_radar.connectors.base import BaseConnector, PostHandler
from event_radar.db import Repository
from event_radar.models import AccountConfig, CanonicalPost, SourcePlatform
from event_radar.utils import is_newer_id, parse_datetime, utc_now


class XConnector(BaseConnector):
    _STREAM_RATE_LIMIT_FALLBACK_SECONDS = 60.0
    _STREAM_RATE_LIMIT_MIN_SECONDS = 15.0
    _STREAM_RATE_LIMIT_MAX_SECONDS = 900.0

    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository,
        on_post: PostHandler,
        on_activity=None,
    ) -> None:
        super().__init__(settings=settings, repository=repository, on_post=on_post, on_activity=on_activity)
        self._client = httpx.AsyncClient(base_url=settings.x_api_base_url, timeout=30.0)

    @property
    def name(self) -> str:
        return "x"

    @property
    def poll_sleep_seconds(self) -> float:
        return self.settings.x_backfill_poll_seconds

    async def close(self) -> None:
        await self._client.aclose()

    async def run(self, stop_event: asyncio.Event) -> None:
        accounts = await self.repository.list_accounts(active_only=True, source=SourcePlatform.X)
        enabled = bool(accounts) and self.settings.x_stream_enabled
        auth_configured = self.settings.x_bearer_token is not None
        self.mark_running(enabled=enabled, auth_configured=auth_configured, detail="starting")
        if not enabled or not auth_configured:
            if not accounts:
                self.status.detail = "no_active_accounts"
            elif not auth_configured:
                self.status.detail = "missing_x_bearer_token"
            await self.emit_activity("warning", "X connector inactive", self.status.detail or "inactive")
            await stop_event.wait()
            return
        await self.emit_activity("info", "X connector starting", "Starting filtered stream, rule sync, and catch-up polling.")
        tasks = [
            asyncio.create_task(self._stream_loop(stop_event)),
            asyncio.create_task(self._backfill_loop(stop_event)),
            asyncio.create_task(self._rule_sync_loop(stop_event)),
        ]
        try:
            await stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.status.running = False

    async def _rule_sync_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.sync_rules()
                self.mark_success(detail="rules_synced", when=utc_now())
                await self.emit_activity("info", "X rules synced", "Filtered stream rules synchronized.")
            except Exception as exc:  # noqa: BLE001
                self.mark_error(f"rule_sync_failed: {exc}")
                await self.emit_activity("error", "X rule sync failed", str(exc))
            if await self.sleep_or_stop(stop_event, self.settings.x_rule_sync_seconds):
                return

    async def sync_rules(self) -> None:
        accounts = await self.repository.list_accounts(active_only=True, source=SourcePlatform.X)
        desired = {
            f"event-radar:{account.id}": {"value": f"from:{account.handle}", "tag": f"event-radar:{account.id}"}
            for account in accounts
        }
        existing_resp = await self._client.get("/2/tweets/search/stream/rules", headers=self._headers())
        await self._record_api_request(
            endpoint="/2/tweets/search/stream/rules",
            method="GET",
            request_kind="read",
            response=existing_resp,
        )
        existing_resp.raise_for_status()
        existing = existing_resp.json().get("data", [])
        to_delete = [
            item["id"]
            for item in existing
            if item.get("tag", "").startswith("event-radar:") and item.get("tag") not in desired
        ]
        to_add = [rule for tag, rule in desired.items() if tag not in {item.get("tag") for item in existing}]
        if to_delete:
            resp = await self._client.post(
                "/2/tweets/search/stream/rules",
                headers=self._headers(),
                json={"delete": {"ids": to_delete}},
            )
            await self._record_api_request(
                endpoint="/2/tweets/search/stream/rules",
                method="POST",
                request_kind="write",
                response=resp,
                metadata={"delete_count": len(to_delete)},
            )
            resp.raise_for_status()
        if to_add:
            resp = await self._client.post(
                "/2/tweets/search/stream/rules",
                headers=self._headers(),
                json={"add": to_add},
            )
            await self._record_api_request(
                endpoint="/2/tweets/search/stream/rules",
                method="POST",
                request_kind="write",
                response=resp,
                metadata={"add_count": len(to_add)},
            )
            resp.raise_for_status()

    async def _stream_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            accounts = await self.repository.list_accounts(active_only=True, source=SourcePlatform.X)
            account_by_id = {account.id: account for account in accounts}
            if not accounts:
                if await self.sleep_or_stop(stop_event, 10.0):
                    return
                continue
            try:
                params = {
                    "tweet.fields": "created_at,author_id,entities,referenced_tweets,attachments",
                    "expansions": "author_id,attachments.media_keys",
                    "user.fields": "name,username,verified",
                    "media.fields": "url,preview_image_url",
                }
                async with self._client.stream(
                    "GET",
                    "/2/tweets/search/stream",
                    headers=self._headers(),
                    params=params,
                ) as response:
                    response.raise_for_status()
                    await self._record_api_request(
                        endpoint="/2/tweets/search/stream",
                        method="GET",
                        request_kind="read",
                        response=response,
                    )
                    self.mark_success(detail="stream_connected", when=utc_now())
                    await self.emit_activity("info", "X stream connected", "Connected to the X filtered stream.")
                    async for line in response.aiter_lines():
                        if stop_event.is_set():
                            return
                        if not line:
                            continue
                        payload = json.loads(line)
                        post = self.normalize_stream_payload(payload, account_by_id)
                        if post is None:
                            continue
                        account = account_by_id[post.account_db_id]
                        await self.on_post(self.name, account, post)
                        self.mark_success(detail="stream_event_received", when=utc_now())
            except httpx.HTTPStatusError as exc:
                await self._record_api_request(
                    endpoint="/2/tweets/search/stream",
                    method="GET",
                    request_kind="read",
                    response=exc.response,
                )
                if exc.response.status_code == 429:
                    retry_seconds = self._stream_retry_after_seconds(exc.response)
                    self._mark_stream_rate_limited(retry_seconds)
                    await self.emit_activity(
                        "warning",
                        "X stream rate limited",
                        f"Filtered stream hit a rate limit; retrying in {int(retry_seconds)} seconds.",
                        metadata={
                            "status_code": 429,
                            "retry_seconds": retry_seconds,
                            "retry_after": exc.response.headers.get("Retry-After"),
                        },
                    )
                    if await self.sleep_or_stop(stop_event, retry_seconds):
                        return
                    continue
                self.mark_error(f"stream_loop_failed: {exc}")
                await self.emit_activity("error", "X stream loop failed", str(exc))
                if await self.sleep_or_stop(stop_event, 5.0):
                    return
            except Exception as exc:  # noqa: BLE001
                self.mark_error(f"stream_loop_failed: {exc}")
                await self.emit_activity("error", "X stream loop failed", str(exc))
                if await self.sleep_or_stop(stop_event, 5.0):
                    return

    async def _backfill_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            accounts = await self.repository.list_accounts(active_only=True, source=SourcePlatform.X)
            for account in accounts:
                if stop_event.is_set():
                    return
                try:
                    await self._poll_account(account)
                    self.mark_success(detail=f"backfill_ok:{account.handle}", when=utc_now())
                except Exception as exc:  # noqa: BLE001
                    self.mark_error(f"backfill_failed:{account.handle}:{exc}")
                    await self.emit_activity("error", "X catch-up failed", f"{account.handle}: {exc}")
            if await self.sleep_or_stop(stop_event, self.settings.x_backfill_poll_seconds):
                return

    async def _poll_account(self, account: AccountConfig) -> None:
        source_account_id = account.source_account_id or await self._resolve_user_id(account)
        checkpoint = await self.repository.get_checkpoint(self.name, account.id)
        params = {
            "max_results": 10,
            "tweet.fields": "created_at,author_id,entities,referenced_tweets,attachments",
            "expansions": "author_id,attachments.media_keys",
            "media.fields": "url,preview_image_url",
        }
        if checkpoint and checkpoint.get("last_source_post_id"):
            params["since_id"] = checkpoint["last_source_post_id"]
        endpoint = f"/2/users/{source_account_id}/tweets"
        response = await self._client.get(endpoint, headers=self._headers(), params=params)
        await self._record_api_request(
            endpoint=endpoint,
            method="GET",
            request_kind="read",
            response=response,
            metadata={"account_id": account.id, "handle": account.handle},
        )
        response.raise_for_status()
        payload = response.json()
        includes = payload.get("includes", {})
        media_by_key = {item["media_key"]: item for item in includes.get("media", [])}
        for item in reversed(payload.get("data", [])):
            post = self.normalize_tweet_payload(item, account, media_by_key)
            await self.on_post(self.name, account, post)

    async def _resolve_user_id(self, account: AccountConfig) -> str:
        endpoint = f"/2/users/by/username/{account.handle}"
        response = await self._client.get(endpoint, headers=self._headers())
        await self._record_api_request(
            endpoint=endpoint,
            method="GET",
            request_kind="read",
            response=response,
            metadata={"account_id": account.id, "handle": account.handle},
        )
        response.raise_for_status()
        data = response.json()["data"]
        user_id = str(data["id"])
        await self.repository.resolve_account_identity(account.id, user_id, f"https://x.com/{account.handle}")
        return user_id

    def normalize_stream_payload(
        self,
        payload: dict[str, Any],
        account_by_id: dict[str, AccountConfig],
    ) -> CanonicalPost | None:
        matching_rules = payload.get("matching_rules", [])
        if not matching_rules or "data" not in payload:
            return None
        tag = matching_rules[0].get("tag", "")
        account_id = tag.removeprefix("event-radar:")
        account = account_by_id.get(account_id)
        if account is None:
            return None
        includes = payload.get("includes", {})
        media_by_key = {item["media_key"]: item for item in includes.get("media", [])}
        return self.normalize_tweet_payload(payload["data"], account, media_by_key)

    def normalize_tweet_payload(
        self,
        item: dict[str, Any],
        account: AccountConfig,
        media_by_key: dict[str, dict[str, Any]],
    ) -> CanonicalPost:
        links = [entry.get("expanded_url") or entry.get("url") for entry in item.get("entities", {}).get("urls", []) if entry.get("expanded_url") or entry.get("url")]
        media_urls = [
            media.get("url") or media.get("preview_image_url")
            for key in item.get("attachments", {}).get("media_keys", [])
            if (media := media_by_key.get(key))
        ]
        referenced = item.get("referenced_tweets", [])
        published_at = parse_datetime(item.get("created_at")) or utc_now()
        return CanonicalPost(
            source=SourcePlatform.X,
            account_db_id=account.id,
            source_account_id=str(item.get("author_id") or account.source_account_id or account.handle),
            display_name=account.display_name,
            handle=account.handle,
            source_post_id=str(item["id"]),
            canonical_url=f"https://x.com/{account.handle}/status/{item['id']}",
            text=item.get("text", "").strip(),
            links=links,
            media_urls=[url for url in media_urls if url],
            is_reply=any(ref.get("type") == "replied_to" for ref in referenced),
            is_repost=any(ref.get("type") == "retweeted" for ref in referenced),
            published_at=published_at.astimezone(UTC),
            observed_at=utc_now(),
            raw_payload=item,
            collector_metadata={"connector": self.name},
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.x_bearer_token.get_secret_value()}"}

    def _stream_retry_after_seconds(self, response: httpx.Response) -> float:
        retry_after = (response.headers.get("Retry-After") or "").strip()
        if retry_after.isdigit():
            return self._clamp_stream_retry_seconds(float(retry_after))
        if retry_after:
            try:
                retry_at = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError, IndexError):
                retry_at = None
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay_seconds = (retry_at.astimezone(UTC) - utc_now()).total_seconds()
                if delay_seconds > 0:
                    return self._clamp_stream_retry_seconds(delay_seconds)
        return self._clamp_stream_retry_seconds(
            max(self.settings.x_rule_sync_seconds, self._STREAM_RATE_LIMIT_FALLBACK_SECONDS)
        )

    def _clamp_stream_retry_seconds(self, seconds: float) -> float:
        return min(max(seconds, self._STREAM_RATE_LIMIT_MIN_SECONDS), self._STREAM_RATE_LIMIT_MAX_SECONDS)

    def _mark_stream_rate_limited(self, retry_seconds: float) -> None:
        rounded_seconds = max(1, int(retry_seconds))
        self.status.running = True
        self.status.last_error = None
        self.status.detail = f"stream_rate_limited_retrying_in:{rounded_seconds}s"
        self.logger.warning("x stream rate limited; retrying in %.1f seconds", retry_seconds)

    async def _record_api_request(
        self,
        *,
        endpoint: str,
        method: str,
        request_kind: str,
        response: httpx.Response,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self.repository.record_api_request(
                provider="x",
                endpoint=endpoint,
                method=method,
                request_kind=request_kind,
                status_code=response.status_code,
                metadata=metadata,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception("failed to persist X API request usage")
