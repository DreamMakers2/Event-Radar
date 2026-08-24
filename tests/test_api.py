from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from event_radar.classifier import ClassificationUnavailableError
from event_radar.main import create_app
from event_radar.models import (
    AlertResult,
    AnalysisRecord,
    ClassifierOutput,
    AssetImpactPrediction,
    CanonicalPost,
    ManualEventTestRequest,
    MarketImpactDirection,
    MarketImpactSnapshot,
    ScoringBreakdown,
    SourcePlatform,
)
from event_radar.service import EventRadarService
from event_radar.utils import utc_now


async def seed_event(service) -> tuple[int, str]:
    account = (await service.list_accounts())[0]
    published_at = utc_now()
    observed_at = utc_now()
    post = CanonicalPost(
        source=SourcePlatform.X,
        account_db_id=account.id,
        source_account_id="1000",
        display_name=account.display_name,
        handle=account.handle,
        source_post_id="post-1000",
        canonical_url=f"https://x.com/{account.handle}/status/post-1000",
        text="Diplomatic talks resume in Geneva this afternoon.",
        published_at=published_at,
        observed_at=observed_at,
        raw_payload={},
    )
    normalized_post_id, inserted = await service.repository.save_post(post)
    assert inserted
    analysis = AnalysisRecord(
        normalized_post_id=normalized_post_id,
        model="gpt-5-mini",
        summary="Diplomatic talks resume in Geneva.",
        categories=["diplomacy"],
        reasoning="High-profile actor and immediate diplomatic significance.",
        breakdown=ScoringBreakdown(
            actor_importance=85,
            event_severity=76,
            immediacy=80,
            novelty=68,
            wider_impact=79,
        ),
        market_impacts=seed_market_impacts(),
        total_score=78.9,
        threshold=70,
        decision="alerted",
        input_tokens=120,
        output_tokens=35,
        request_cost_usd=0.04,
        created_at=utc_now(),
    )
    analysis_id = await service.repository.save_analysis(analysis)
    await service.repository.save_alert(
        normalized_post_id,
        analysis_id,
        AlertResult(
            status="sent",
            message_text="Sent to relay.",
            relay_response={"ok": True},
            sent_at=utc_now(),
            acked_at=utc_now(),
        ),
    )
    return normalized_post_id, account.handle


def seed_market_impacts() -> MarketImpactSnapshot:
    return MarketImpactSnapshot(
        dxy=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=72),
        btc=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=71),
        dow=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=68),
        spx=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=70),
        ndx=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=74),
        oil=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=77),
        metals=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=59),
        energy=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=75),
        nvda=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=76),
        aapl=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=67),
        msft=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=68),
        tsla=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=73),
        intc=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=65),
        asml=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=69),
        pltr=AssetImpactPrediction(direction=MarketImpactDirection.FLAT, confidence=45),
    )


def test_api_health_and_account_crud(settings) -> None:
    app = create_app(settings)
    async def fake_x_usage(*, days: int = 30) -> dict[str, object]:
        return {
            "status": "ok",
            "days": days,
            "project_id": "project-1",
            "project_cap": 2_000_000,
            "project_usage": 97,
            "cap_reset_day": 26,
            "daily_usage": [
                {"date": "2026-03-27T00:00:00.000Z", "consumed": 81},
                {"date": "2026-03-29T00:00:00.000Z", "consumed": 16},
            ],
            "consumed_last_7d": 97,
            "consumed_last_30d": 97,
        }

    app.state.service.billing.fetch_x_post_usage = fake_x_usage  # type: ignore[method-assign]
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.headers["content-security-policy"]
        overview = client.get("/api/v1/overview")
        assert overview.status_code == 200
        assert "costs" in overview.json()
        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["summary"]["status"] == "ok"
        accounts = client.get("/api/v1/accounts")
        assert accounts.status_code == 200
        assert accounts.json()
        create = client.post(
            "/api/v1/accounts",
            json={
                "source": "x",
                "entity_key": "custom_entity",
                "display_name": "Custom Entity",
                "handle": "customhandle",
                "authority_rank": 55,
            },
        )
        assert create.status_code == 200
        update = client.patch(
            f"/api/v1/accounts/{create.json()['id']}",
            json={"active": False, "alert_threshold": 90},
        )
        assert update.status_code == 200
        assert update.json()["active"] is False
        assert update.json()["alert_threshold"] == 90
        duplicate = client.post(
            "/api/v1/accounts",
            json={
                "source": "x",
                "entity_key": "custom_entity",
                "display_name": "Custom Entity",
                "handle": "customhandle",
                "authority_rank": 55,
            },
        )
        assert duplicate.status_code == 409


def test_events_filters_detail_and_root_app(settings) -> None:
    app = create_app(settings)
    async def fake_x_usage(*, days: int = 30) -> dict[str, object]:
        return {
            "status": "ok",
            "days": days,
            "project_id": "project-1",
            "project_cap": 2_000_000,
            "project_usage": 97,
            "cap_reset_day": 26,
            "daily_usage": [
                {"date": "2026-03-27T00:00:00.000Z", "consumed": 81},
                {"date": "2026-03-29T00:00:00.000Z", "consumed": 16},
            ],
            "consumed_last_7d": 97,
            "consumed_last_30d": 97,
        }

    app.state.service.billing.fetch_x_post_usage = fake_x_usage  # type: ignore[method-assign]
    with TestClient(app) as client:
        async def fake_analyze(_post):
            return (
                ClassifierOutput(
                    summary="Military coordination talks resume after an overnight strike and new sanctions warning.",
                    categories=["military", "sanctions", "diplomacy"],
                    reasoning="The combination of escalation language and sanctions expectations can move risk assets quickly.",
                    breakdown=ScoringBreakdown(
                        actor_importance=88,
                        event_severity=78,
                        immediacy=82,
                        novelty=70,
                        wider_impact=84,
                    ),
                    market_impacts=seed_market_impacts(),
                ),
                80.8,
                {"mode": "model", "output_text": "{}"},
            )

        client.app.state.service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
        normalized_post_id, handle = asyncio.run(seed_event(client.app.state.service))

        root = client.get("/")
        assert root.status_code == 200
        assert "Event Radar" in root.text

        events = client.get("/api/v1/events", params={"source": "x", "q": "Geneva"})
        assert events.status_code == 200
        assert len(events.json()) == 1
        assert events.json()[0]["normalized_post_id"] == normalized_post_id
        assert events.json()[0]["feedback_vote"] is None

        vote = client.patch(f"/api/v1/events/{normalized_post_id}/vote", json={"vote": "up"})
        assert vote.status_code == 200
        assert vote.json()["feedback_vote"] == "up"

        clear_vote = client.patch(f"/api/v1/events/{normalized_post_id}/vote", json={"vote": None})
        assert clear_vote.status_code == 200
        assert clear_vote.json()["feedback_vote"] is None

        detail = client.get(f"/api/v1/events/{normalized_post_id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["analysis"]["summary"] == "Diplomatic talks resume in Geneva."
        assert payload["analysis"]["market_impacts"]["btc"]["direction"] == "up"
        assert payload["alert"]["status"] == "sent"
        assert payload["feedback_vote"] is None

        test_trigger = client.post(
            "/api/v1/events/test-trigger",
            json={
                "handle": handle,
                "message": "Military coordination talks resume after an overnight strike and new sanctions warning.",
            },
        )
        assert test_trigger.status_code == 200
        simulation = test_trigger.json()
        assert simulation["account"]["handle"] == handle
        assert simulation["analysis"]["summary"]
        assert simulation["analysis"]["mode"] == "model"
        assert "market_impacts" in simulation["analysis"]
        assert simulation["outcome"]["status"] in {"sent", "dry_run", "suppressed", "failed"}


def test_event_operations_and_dashboard_reset_endpoints(settings) -> None:
    app = create_app(settings)
    async def fake_x_usage(*, days: int = 30) -> dict[str, object]:
        return {
            "status": "ok",
            "days": days,
            "project_id": "project-1",
            "project_cap": 2_000_000,
            "project_usage": 97,
            "cap_reset_day": 26,
            "daily_usage": [
                {"date": "2026-03-27T00:00:00.000Z", "consumed": 81},
                {"date": "2026-03-29T00:00:00.000Z", "consumed": 16},
            ],
            "consumed_last_7d": 97,
            "consumed_last_30d": 97,
        }

    app.state.service.billing.fetch_x_post_usage = fake_x_usage  # type: ignore[method-assign]
    with TestClient(app) as client:
        service = client.app.state.service

        async def fake_analyze(_post):
            return (
                ClassifierOutput(
                    summary="Refreshed diplomatic talks resume in Geneva.",
                    categories=["diplomacy"],
                    reasoning="Re-run classification keeps the event above threshold.",
                    breakdown=ScoringBreakdown(
                        actor_importance=85,
                        event_severity=82,
                        immediacy=80,
                        novelty=70,
                        wider_impact=83,
                    ),
                    market_impacts=seed_market_impacts(),
                ),
                80.9,
                {"mode": "model", "output_text": "{}"},
            )

        service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
        normalized_post_id, _handle = asyncio.run(seed_event(service))
        asyncio.run(
            service.record_activity(
                "connector",
                "warning",
                "truth_social",
                "Connector warning",
                "Session cookie needs refresh.",
            )
        )

        refresh_response = client.post(f"/api/v1/events/{normalized_post_id}/refresh")
        assert refresh_response.status_code == 200
        assert refresh_response.json()["analysis"]["total_score"] == 80.9

        clear_attention = client.delete("/api/v1/activity/attention")
        assert clear_attention.status_code == 200
        assert clear_attention.json()["deleted"] >= 1

        clear_activity = client.delete("/api/v1/activity")
        assert clear_activity.status_code == 200
        assert clear_activity.json()["deleted"] >= 1

        reset_latency = client.delete("/api/v1/metrics/latency")
        assert reset_latency.status_code == 200
        assert reset_latency.json()["deleted"] >= 1

        delete_response = client.delete(f"/api/v1/events/{normalized_post_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["ok"] is True

        missing_detail = client.get(f"/api/v1/events/{normalized_post_id}")
        assert missing_detail.status_code == 404


def test_dashboard_stays_available_when_project_scoped_openai_cost_lookup_fails(settings) -> None:
    app = create_app(settings)

    async def fake_x_usage(*, days: int = 30) -> dict[str, object]:
        return {
            "status": "ok",
            "days": days,
            "project_id": "project-1",
            "project_cap": 2_000_000,
            "project_usage": 97,
            "cap_reset_day": 26,
            "daily_usage": [
                {"date": "2026-03-27T00:00:00.000Z", "consumed": 81},
                {"date": "2026-03-29T00:00:00.000Z", "consumed": 16},
            ],
            "consumed_last_7d": 97,
            "consumed_last_30d": 97,
        }

    async def fake_openai_scope() -> dict[str, object]:
        return {
            "status": "ok",
            "api_key_id": "key_event_radar",
            "api_key_name": "Event Radar",
            "api_key_last_used_at": None,
            "project_id": "proj_event_radar",
            "project_name": "Event Radar",
            "project_api_key_count": 1,
        }

    async def fake_project_costs(*, days: int = 31, project_ids: list[str] | None = None) -> dict[str, object]:
        assert days == 31
        assert project_ids == ["proj_event_radar"]
        return {
            "status": "unavailable",
            "reason": "http_429",
            "days": days,
            "project_ids": project_ids or [],
        }

    app.state.service.billing.fetch_x_post_usage = fake_x_usage  # type: ignore[method-assign]
    app.state.service.billing.resolve_openai_api_key_scope = fake_openai_scope  # type: ignore[method-assign]
    app.state.service.billing.fetch_organization_costs = fake_project_costs  # type: ignore[method-assign]

    with TestClient(app) as client:
        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        payload = dashboard.json()
        assert payload["costs"]["openai"]["scope"]["project_name"] == "Event Radar"
        assert payload["costs"]["openai"]["scope"]["api_key_name"] == "Event Radar"
        assert payload["costs"]["openai"]["usage"]["last_30d"]["analysis_count"] == 0
        assert payload["costs"]["openai"]["billed_costs"]["status"] == "unavailable"
        assert payload["costs"]["openai"]["billed_costs"]["reason"] == "http_429"


@pytest.mark.asyncio
async def test_cost_summary_uses_local_openai_usage_when_project_scoped_usage_is_stale(settings) -> None:
    settings.openai_admin_key = SecretStr("admin-key")
    service = EventRadarService(settings)
    await service.repository.initialize()
    await seed_event(service)

    async def fake_fx() -> tuple[float, str]:
        return 0.9, "2026-03-29"

    async def fake_credit() -> dict[str, object]:
        return {"status": "unavailable", "reason": "browser_session_required"}

    async def fake_x_usage(*, days: int = 30) -> dict[str, object]:
        return {"status": "unavailable", "reason": "missing_x_bearer_token", "days": days}

    async def fake_openai_scope() -> dict[str, object]:
        return {
            "status": "ok",
            "api_key_id": "key_event_radar",
            "api_key_name": "Event Radar",
            "api_key_last_used_at": None,
            "project_id": "proj_event_radar",
            "project_name": "Event Radar",
            "project_api_key_count": 1,
        }

    async def fake_project_costs(*, days: int = 31, project_ids: list[str] | None = None) -> dict[str, object]:
        assert days == 31
        assert project_ids == ["proj_event_radar"]
        return {
            "status": "ok",
            "days": days,
            "project_ids": project_ids or [],
            "billed_last_7d_usd": 0.0,
            "billed_last_30d_usd": 0.0,
        }

    async def fail_openai_usage(*, days: int, api_key_id: str | None) -> dict[str, object]:
        raise AssertionError("cost_summary should use local persisted usage instead of org key usage")

    service.billing.eur_per_usd = fake_fx  # type: ignore[method-assign]
    service.billing.fetch_available_credit = fake_credit  # type: ignore[method-assign]
    service.billing.fetch_x_post_usage = fake_x_usage  # type: ignore[method-assign]
    service.billing.resolve_openai_api_key_scope = fake_openai_scope  # type: ignore[method-assign]
    service.billing.fetch_organization_costs = fake_project_costs  # type: ignore[method-assign]
    service.billing.fetch_openai_key_usage = fail_openai_usage  # type: ignore[method-assign]

    summary = await service.cost_summary()

    assert summary["openai"]["usage"]["status"] == "ok"
    assert summary["openai"]["usage"]["last_30d"]["analysis_count"] == 1
    assert summary["openai"]["usage"]["last_30d"]["input_tokens"] == 120
    assert summary["openai"]["usage"]["last_30d"]["output_tokens"] == 35
    assert summary["openai"]["costs"]["estimated_last_30d_usd"] == pytest.approx(0.04)
    assert summary["openai"]["costs"]["estimated_last_30d_eur"] == pytest.approx(0.036)
    assert summary["openai"]["billed_costs"]["status"] == "unavailable"
    assert summary["openai"]["billed_costs"]["reason"] == "configured_project_no_recent_activity"


@pytest.mark.asyncio
async def test_manual_trigger_alerts_when_model_score_clears_new_default_threshold(settings) -> None:
    service = EventRadarService(settings)
    await service.repository.initialize()

    async def fake_analyze(_post):
        return (
            ClassifierOutput(
                summary="Former President Trump posts an urgent claim that China is preparing to invade Taiwan and urges immediate U.S. intervention.",
                categories=["military", "diplomacy", "domestic_politics"],
                reasoning=(
                    "High-profile actor making an urgent, alarmist claim about a potential China-Taiwan conflict "
                    "increases perceived escalation risk, but it is short on evidence and repeats a recurring narrative."
                ),
                breakdown=ScoringBreakdown(
                    actor_importance=85,
                    event_severity=70,
                    immediacy=60,
                    novelty=30,
                    wider_impact=75,
                ),
                market_impacts=seed_market_impacts(),
            ),
            65.75,
            {"mode": "model", "output_text": "{}"},
        )

    service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
    try:
        result = await service.simulate_event_trigger(
            ManualEventTestRequest(handle="realDonaldTrump", message="china preparing for taiwan invasion. must intervene NOW")
        )
    finally:
        await service.classifier.close()
        await service.relay.close()

    assert result is not None
    assert result.analysis.mode == "model"
    assert result.analysis.total_score == 65.75
    assert result.analysis.decision == "alerted"
    assert result.outcome.status == "dry_run"
    assert result.outcome.reason is None


@pytest.mark.asyncio
async def test_manual_trigger_respects_model_below_threshold_for_ground_force_presence_claim(settings) -> None:
    service = EventRadarService(settings)
    await service.repository.initialize()

    async def fake_analyze(_post):
        return (
            ClassifierOutput(
                summary=(
                    'Donald Trump posts a terse claim - "iran boots on the ground." - implying Iranian ground operations or involvement.'
                ),
                categories=["military", "diplomacy", "domestic_politics"],
                reasoning=(
                    "High-profile actor makes a brief, unsourced assertion implying Iranian ground military action. "
                    "The post is ambiguous, so novelty is low even though it could quickly move sentiment if amplified."
                ),
                breakdown=ScoringBreakdown(
                    actor_importance=85,
                    event_severity=60,
                    immediacy=70,
                    novelty=30,
                    wider_impact=60,
                ),
                market_impacts=seed_market_impacts(),
            ),
            62.5,
            {"mode": "model", "output_text": "{}"},
        )

    service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
    try:
        result = await service.simulate_event_trigger(
            ManualEventTestRequest(handle="realDonaldTrump", message="iran boots on the ground.")
        )
    finally:
        await service.classifier.close()
        await service.relay.close()

    assert result is not None
    assert result.analysis.mode == "model"
    assert result.analysis.total_score == 62.5
    assert result.analysis.decision == "below_threshold"
    assert result.outcome.status == "suppressed"
    assert result.outcome.reason == "below_threshold"


@pytest.mark.asyncio
async def test_manual_trigger_respects_model_below_threshold_for_semiconductor_policy_signal(settings) -> None:
    service = EventRadarService(settings)
    await service.repository.initialize()

    async def fake_analyze(_post):
        return (
            ClassifierOutput(
                summary=(
                    "Former President Trump posted 'expanding chip manufacturing', signaling intent or support for increased domestic semiconductor capacity."
                ),
                categories=["economy", "domestic_politics", "industry"],
                reasoning=(
                    "High-profile political actor signaling support for expanded semiconductor production could move chipmaker and industrial-policy expectations, "
                    "but the message is terse and leaves details unclear."
                ),
                breakdown=ScoringBreakdown(
                    actor_importance=80,
                    event_severity=45,
                    immediacy=40,
                    novelty=40,
                    wider_impact=60,
                ),
                market_impacts=seed_market_impacts(),
            ),
            52.5,
            {"mode": "model", "output_text": "{}"},
        )

    service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
    try:
        result = await service.simulate_event_trigger(
            ManualEventTestRequest(handle="realDonaldTrump", message="expanding chip manufacturing")
        )
    finally:
        await service.classifier.close()
        await service.relay.close()

    assert result is not None
    assert result.analysis.mode == "model"
    assert result.analysis.total_score == 52.5
    assert result.analysis.decision == "below_threshold"
    assert result.outcome.status == "suppressed"
    assert result.outcome.reason == "below_threshold"


@pytest.mark.asyncio
async def test_manual_trigger_respects_model_below_threshold_for_crypto_policy_signal(settings) -> None:
    service = EventRadarService(settings)
    await service.repository.initialize()

    async def fake_analyze(_post):
        return (
            ClassifierOutput(
                summary=(
                    "Former President Trump calls for Bitcoin and cryptocurrency legislation at both state and federal levels."
                ),
                categories=["domestic_politics", "economy", "cyber"],
                reasoning=(
                    "A high-profile political principal publicly urging comprehensive crypto legislation can prompt immediate policy discussions, "
                    "lobbying, and market repricing even before formal proposals."
                ),
                breakdown=ScoringBreakdown(
                    actor_importance=80,
                    event_severity=55,
                    immediacy=50,
                    novelty=45,
                    wider_impact=65,
                ),
                market_impacts=seed_market_impacts(),
            ),
            61.25,
            {"mode": "model", "output_text": "{}"},
        )

    service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
    try:
        result = await service.simulate_event_trigger(
            ManualEventTestRequest(
                handle="realDonaldTrump",
                message="bitcoin and cryptocurrency legislation at both state and federal levels",
            )
        )
    finally:
        await service.classifier.close()
        await service.relay.close()

    assert result is not None
    assert result.analysis.mode == "model"
    assert result.analysis.total_score == 61.25
    assert result.analysis.decision == "below_threshold"
    assert result.outcome.status == "suppressed"
    assert result.outcome.reason == "below_threshold"


@pytest.mark.asyncio
async def test_manual_trigger_preserves_non_market_signal_below_threshold(settings) -> None:
    service = EventRadarService(settings)
    await service.repository.initialize()

    async def fake_analyze(_post):
        return (
            ClassifierOutput(
                summary="Donald Trump posts a generic greeting.",
                categories=["media"],
                reasoning="A high-profile actor posted a generic message with little concrete market relevance.",
                breakdown=ScoringBreakdown(
                    actor_importance=85,
                    event_severity=20,
                    immediacy=25,
                    novelty=25,
                    wider_impact=20,
                ),
                market_impacts=MarketImpactSnapshot.flat(confidence=30),
            ),
            31.5,
            {"mode": "model", "output_text": "{}"},
        )

    service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
    try:
        result = await service.simulate_event_trigger(
            ManualEventTestRequest(handle="realDonaldTrump", message="hello everyone")
        )
    finally:
        await service.classifier.close()
        await service.relay.close()

    assert result is not None
    assert result.analysis.mode == "model"
    assert result.analysis.total_score == 31.5
    assert result.analysis.decision == "below_threshold"
    assert result.outcome.status == "suppressed"
    assert result.outcome.reason == "below_threshold"


@pytest.mark.asyncio
async def test_manual_trigger_requires_openai_when_not_configured(settings) -> None:
    service = EventRadarService(settings)
    await service.repository.initialize()

    with pytest.raises(ClassificationUnavailableError) as exc_info:
        await service.simulate_event_trigger(
            ManualEventTestRequest(
                handle="realDonaldTrump",
                message="bitcoin and cryptocurrency legislation at both state and federal levels",
            )
        )
    await service.classifier.close()
    await service.relay.close()

    assert exc_info.value.reason == "missing_openai_api_key"


def test_manual_trigger_endpoint_returns_503_when_openai_is_not_configured(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/events/test-trigger",
            json={
                "handle": "realDonaldTrump",
                "message": "bitcoin and cryptocurrency legislation at both state and federal levels",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "missing_openai_api_key"


def test_manual_trigger_endpoint_returns_503_when_openai_request_fails(settings) -> None:
    app = create_app(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))
    with TestClient(app) as client:
        async def fake_analyze(_post):
            raise ClassificationUnavailableError("openai_classification_failed", "503 error from Responses API")

        client.app.state.service.classifier.analyze = fake_analyze  # type: ignore[method-assign]
        response = client.post(
            "/api/v1/events/test-trigger",
            json={
                "handle": "realDonaldTrump",
                "message": "bitcoin and cryptocurrency legislation at both state and federal levels",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "openai_classification_failed"
