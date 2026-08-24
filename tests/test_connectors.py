from __future__ import annotations

import asyncio
import httpx
import pytest

from event_radar.connectors.truth_social import TruthSocialConnector, TruthSocialRateLimitError
from event_radar.connectors.x import XConnector
from event_radar.models import AccountCreateRequest
from event_radar.db import Repository
from event_radar.models import AccountConfig, SourcePlatform
from event_radar.utils import utc_now


def build_account(source: SourcePlatform) -> AccountConfig:
    now = utc_now()
    return AccountConfig(
        id=f"{source.value}_acc",
        source=source,
        entity_key="entity",
        display_name="Display",
        handle="handle",
        authority_rank=80,
        created_at=now,
        updated_at=now,
    )


class FakeTruthSocialBrowserClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def fetch_account_statuses(
        self,
        *,
        handle: str,
        source_account_id: str | None,
        limit: int,
        exclude_replies: bool,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "handle": handle,
                "source_account_id": source_account_id,
                "limit": limit,
                "exclude_replies": exclude_replies,
            }
        )
        return self.payload

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_x_poll_account_fetches_recent_posts(settings, tmp_path) -> None:
    repository = Repository(tmp_path / "db.sqlite3")
    await repository.initialize()
    account = await repository.create_account(
        AccountCreateRequest(
            source=SourcePlatform.X,
            entity_key="entity",
            display_name="Display",
            handle="handle",
            authority_rank=80,
        )
    )
    seen = []

    async def on_post(connector_name, account_obj, post):
        seen.append((connector_name, account_obj.handle, post.source_post_id))

    connector = XConnector(settings=settings, repository=repository, on_post=on_post)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/by/username/handle"):
            return httpx.Response(200, json={"data": {"id": "42"}})
        if request.url.path.endswith("/users/42/tweets"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "2", "author_id": "42", "text": "second", "created_at": "2026-03-26T00:00:02Z"},
                        {"id": "1", "author_id": "42", "text": "first", "created_at": "2026-03-26T00:00:01Z"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    connector._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.x.com")
    await connector._poll_account(account)
    await connector.close()
    usage = await repository.api_request_summary(provider="x", request_kind="read")
    assert seen == [("x", "handle", "1"), ("x", "handle", "2")]
    assert usage["request_count"] == 2
    assert usage["successful_request_count"] == 2


@pytest.mark.asyncio
async def test_x_stream_loop_backs_off_on_rate_limit(settings, tmp_path) -> None:
    repository = Repository(tmp_path / "db.sqlite3")
    await repository.initialize()
    await repository.create_account(
        AccountCreateRequest(
            source=SourcePlatform.X,
            entity_key="entity",
            display_name="Display",
            handle="handle",
            authority_rank=80,
        )
    )
    activities = []
    sleep_calls = []

    async def noop(*args, **kwargs):
        return None

    async def on_activity(kind, level, component, title, message, metadata):
        activities.append((kind, level, component, title, message, metadata))

    connector = XConnector(settings=settings, repository=repository, on_post=noop, on_activity=on_activity)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tweets/search/stream"):
            return httpx.Response(429, headers={"Retry-After": "120"}, json={"detail": "rate limited"})
        raise AssertionError(f"Unexpected URL: {request.url}")

    async def fake_sleep_or_stop(stop_event: asyncio.Event, seconds: float | None = None) -> bool:
        sleep_calls.append(seconds)
        return True

    connector.sleep_or_stop = fake_sleep_or_stop  # type: ignore[method-assign]
    connector._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.x.com")

    await connector._stream_loop(asyncio.Event())
    await connector.close()

    assert sleep_calls == [120.0]
    assert connector.status.running is True
    assert connector.status.detail == "stream_rate_limited_retrying_in:120s"
    assert connector.status.last_error is None
    assert activities == [
        (
            "connector",
            "warning",
            "x",
            "X stream rate limited",
            "Filtered stream hit a rate limit; retrying in 120 seconds.",
            {"status_code": 429, "retry_seconds": 120.0, "retry_after": "120"},
        )
    ]


@pytest.mark.asyncio
async def test_truth_social_poll_account_falls_back_to_browser_when_statuses_are_blocked(settings, tmp_path) -> None:
    repository = Repository(tmp_path / "db.sqlite3")
    await repository.initialize()
    account = await repository.create_account(
        AccountCreateRequest(
            source=SourcePlatform.TRUTH_SOCIAL,
            entity_key="entity",
            display_name="Display",
            handle="handle",
            authority_rank=80,
        )
    )

    seen = []

    async def on_post(connector_name, account_obj, post):
        seen.append((connector_name, account_obj.handle, post.source_post_id))

    connector = TruthSocialConnector(settings=settings, repository=repository, on_post=on_post)
    browser_client = FakeTruthSocialBrowserClient(
        {
            "account": {"id": "55", "url": "https://truthsocial.com/@handle"},
            "statuses": [
                {"id": "2", "created_at": "2026-03-26T00:00:02Z", "content": "<p>second</p>", "spoiler_text": ""},
                {"id": "1", "created_at": "2026-03-26T00:00:01Z", "content": "<p>first</p>", "spoiler_text": ""},
            ],
        }
    )
    connector._build_browser_client = lambda: browser_client  # type: ignore[method-assign]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/accounts/lookup"):
            return httpx.Response(200, json={"id": "55", "url": "https://truthsocial.com/@handle"})
        if request.url.path.endswith("/api/v1/accounts/55/statuses"):
            return httpx.Response(403, json={"detail": "forbidden"})
        raise AssertionError(f"Unexpected URL: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://truthsocial.com") as client:
        await connector._poll_account(client, account)

    accounts = await repository.list_accounts(active_only=True, source=SourcePlatform.TRUTH_SOCIAL)
    updated_account = next(item for item in accounts if item.id == account.id)
    assert connector._prefer_browser_fetch is True
    assert connector.status.detail == "browser_backed_polling"
    assert browser_client.calls == [
        {
            "handle": "handle",
            "source_account_id": None,
            "limit": 5,
            "exclude_replies": False,
        }
    ]
    assert seen == [("truth_social", "handle", "1"), ("truth_social", "handle", "2")]
    assert updated_account.source_account_id == "55"


@pytest.mark.asyncio
async def test_truth_social_poll_account_stays_on_browser_mode_after_lookup_block(settings, tmp_path) -> None:
    repository = Repository(tmp_path / "db.sqlite3")
    await repository.initialize()
    account = await repository.create_account(
        AccountCreateRequest(
            source=SourcePlatform.TRUTH_SOCIAL,
            entity_key="entity",
            display_name="Display",
            handle="handle",
            authority_rank=80,
        )
    )

    seen = []

    async def on_post(connector_name, account_obj, post):
        seen.append((connector_name, account_obj.handle, post.source_post_id))

    connector = TruthSocialConnector(settings=settings, repository=repository, on_post=on_post)
    browser_client = FakeTruthSocialBrowserClient(
        {
            "account": {"id": "77", "url": "https://truthsocial.com/@handle"},
            "statuses": [{"id": "9", "created_at": "2026-03-26T00:00:09Z", "content": "<p>browser only</p>", "spoiler_text": ""}],
        }
    )
    connector._build_browser_client = lambda: browser_client  # type: ignore[method-assign]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/accounts/lookup"):
            return httpx.Response(403, json={"detail": "forbidden"})
        raise AssertionError(f"Unexpected URL: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://truthsocial.com") as client:
        await connector._poll_account(client, account)
        await connector._poll_account(client, account)

    assert browser_client.calls == [
        {
            "handle": "handle",
            "source_account_id": None,
            "limit": 5,
            "exclude_replies": False,
        },
        {
            "handle": "handle",
            "source_account_id": None,
            "limit": 5,
            "exclude_replies": False,
        },
    ]
    assert seen == [("truth_social", "handle", "9"), ("truth_social", "handle", "9")]


@pytest.mark.asyncio
async def test_truth_social_run_backs_off_on_rate_limit(settings, tmp_path) -> None:
    repository = Repository(tmp_path / "db.sqlite3")
    await repository.initialize()
    await repository.create_account(
        AccountCreateRequest(
            source=SourcePlatform.TRUTH_SOCIAL,
            entity_key="entity",
            display_name="Display",
            handle="handle",
            authority_rank=80,
        )
    )
    activities = []
    sleep_calls = []

    async def noop(*args, **kwargs):
        return None

    async def on_activity(kind, level, component, title, message, metadata):
        activities.append((kind, level, component, title, message, metadata))

    connector = TruthSocialConnector(settings=settings, repository=repository, on_post=noop, on_activity=on_activity)
    connector._prefer_browser_fetch = True

    async def fake_poll_once():
        raise TruthSocialRateLimitError(retry_seconds=90.0, retry_after="90")

    async def fake_sleep_or_stop(stop_event: asyncio.Event, seconds: float | None = None) -> bool:
        sleep_calls.append(seconds)
        return True

    connector.poll_once = fake_poll_once  # type: ignore[method-assign]
    connector.sleep_or_stop = fake_sleep_or_stop  # type: ignore[method-assign]

    await connector.run(asyncio.Event())

    assert sleep_calls == [90.0]
    assert connector.status.running is True
    assert connector.status.detail == "browser_rate_limited_retrying_in:90s"
    assert connector.status.last_error is None
    assert activities[-1] == (
        "connector",
        "warning",
        "truth_social",
        "Truth Social rate limited",
        "Truth Social hit a rate limit; retrying in 90 seconds.",
        {"retry_seconds": 90.0, "retry_after": "90"},
    )
