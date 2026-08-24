from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from event_radar.classifier import ClassificationUnavailableError, EventClassifier, SCHEMA
from event_radar.config import Settings
from event_radar.models import (
    AccountConfig,
    AnalysisRecord,
    AssetImpactPrediction,
    CanonicalPost,
    MarketImpactDirection,
    MarketImpactSnapshot,
    ScoringBreakdown,
    SourcePlatform,
)
from event_radar.relay import TelegramRelayClient, format_alert_message
from event_radar.utils import utc_now


def sample_post() -> CanonicalPost:
    return CanonicalPost(
        source=SourcePlatform.X,
        account_db_id="acc",
        source_account_id="123",
        display_name="Donald Trump",
        handle="realDonaldTrump",
        source_post_id="999",
        canonical_url="https://x.com/realDonaldTrump/status/999",
        text="A major diplomatic development was announced.",
        published_at=utc_now(),
        observed_at=utc_now(),
        raw_payload={},
    )


def sample_account() -> AccountConfig:
    now = utc_now()
    return AccountConfig(
        id="acc",
        source=SourcePlatform.X,
        entity_key="donald_trump",
        display_name="Donald Trump",
        handle="realDonaldTrump",
        authority_rank=100,
        created_at=now,
        updated_at=now,
    )


def sample_analysis() -> AnalysisRecord:
    return AnalysisRecord(
        normalized_post_id=1,
        model="gpt-5.4-mini",
        summary="Major diplomatic development announced.",
        categories=["diplomacy"],
        reasoning="High-profile actor and immediate diplomatic impact.",
        breakdown=ScoringBreakdown(
            actor_importance=95,
            event_severity=82,
            immediacy=90,
            novelty=70,
            wider_impact=85,
        ),
        market_impacts=sample_market_impacts(),
        total_score=84.1,
        threshold=70,
        decision="alerted",
        created_at=utc_now(),
    )


def post_with_text(text: str, *, handle: str = "realDonaldTrump", display_name: str = "Donald Trump") -> CanonicalPost:
    post = sample_post()
    return post.model_copy(update={"text": text, "handle": handle, "display_name": display_name})


def sample_market_impacts() -> MarketImpactSnapshot:
    return MarketImpactSnapshot(
        dxy=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=79),
        btc=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=72),
        dow=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=70),
        spx=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=73),
        ndx=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=75),
        oil=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=78),
        metals=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=64),
        energy=AssetImpactPrediction(direction=MarketImpactDirection.DOWN, confidence=76),
        nvda=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=76),
        aapl=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=68),
        msft=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=69),
        tsla=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=74),
        intc=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=67),
        asml=AssetImpactPrediction(direction=MarketImpactDirection.UP, confidence=70),
        pltr=AssetImpactPrediction(direction=MarketImpactDirection.FLAT, confidence=43),
    )


def classifier_output_payload() -> str:
    return json.dumps(
        {
            "summary": "Major development",
            "categories": ["diplomacy"],
            "reasoning": "Concise reasoning",
            "breakdown": {
                "actor_importance": 90,
                "event_severity": 80,
                "immediacy": 85,
                "novelty": 60,
                "wider_impact": 88,
            },
            "market_impacts": [
                {"asset": "btc", "direction": "up", "confidence": 72},
                {"asset": "dow", "direction": "up", "confidence": 70},
                {"asset": "spx", "direction": "up", "confidence": 73},
                {"asset": "ndx", "direction": "up", "confidence": 75},
                {"asset": "nvda", "direction": "up", "confidence": 76},
                {"asset": "pltr", "direction": "down", "confidence": 61},
            ],
        }
    )


@pytest.mark.asyncio
async def test_classifier_parses_structured_response(settings) -> None:
    classifier = EventClassifier(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output_text": classifier_output_payload()},
        )

    classifier._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.openai.com/v1")
    parsed, total, raw = await classifier.analyze(sample_post())
    await classifier.close()
    assert parsed.summary == "Major development"
    assert total > 0
    assert raw["mode"] == "model"
    assert parsed.market_impacts.btc.direction == MarketImpactDirection.UP
    assert parsed.market_impacts.oil.direction == MarketImpactDirection.FLAT
    assert raw["output_text"]


@pytest.mark.asyncio
async def test_classifier_retries_truncated_json_response(settings) -> None:
    classifier = EventClassifier(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        if len(requests) == 1:
            assert payload["max_output_tokens"] == 700
            return httpx.Response(
                200,
                json={
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output_text": (
                        '{'
                        '"summary":"Truncated",'
                        '"categories":["diplomacy"],'
                        '"reasoning":"Cut off",'
                        '"breakdown":{"actor_importance":90,"event_severity":80'
                    ),
                },
            )
        assert payload["max_output_tokens"] == 1400
        return httpx.Response(
            200,
            json={"output_text": classifier_output_payload()},
        )

    classifier._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.openai.com/v1")
    parsed, total, raw = await classifier.analyze(sample_post())
    await classifier.close()
    assert len(requests) == 2
    assert parsed.summary == "Major development"
    assert total > 0
    assert raw["mode"] == "model"
    assert raw["output_text"]


@pytest.mark.asyncio
async def test_classifier_requires_openai_api_key(settings) -> None:
    classifier = EventClassifier(settings)
    with pytest.raises(ClassificationUnavailableError) as exc_info:
        await classifier.analyze(
            post_with_text("bitcoin and cryptocurrency legislation at both state and federal levels").model_copy(
                update={"source": SourcePlatform.TRUTH_SOCIAL}
            )
        )
    await classifier.close()

    assert exc_info.value.reason == "missing_openai_api_key"
    assert "OpenAI classification is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_classifier_raises_when_openai_request_fails(settings) -> None:
    classifier = EventClassifier(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "upstream unavailable"}})

    classifier._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.openai.com/v1")
    with pytest.raises(ClassificationUnavailableError) as exc_info:
        await classifier.analyze(sample_post())
    await classifier.close()

    assert exc_info.value.reason == "openai_classification_failed"
    assert "503" in str(exc_info.value)


def test_classifier_prompt_emphasizes_ultra_terse_tradeable_asset_signals(settings) -> None:
    classifier = EventClassifier(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))
    try:
        prompt = classifier._prompt_for_post(  # noqa: SLF001
            post_with_text("Bitcoin").model_copy(update={"source": SourcePlatform.TRUTH_SOCIAL})
        )
        assert "single-word or ultra-terse mention of a directly tradeable asset" in prompt
        assert "posts only 'Bitcoin'" in prompt
        assert "This post is an ultra-terse direct market signal about Bitcoin." in prompt
    finally:
        asyncio.run(classifier.close())


def test_classifier_prompt_emphasizes_policy_expectation_signals(settings) -> None:
    classifier = EventClassifier(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))
    try:
        prompt = classifier._prompt_for_post(  # noqa: SLF001
            post_with_text("bitcoin and cryptocurrency legislation at both state and federal levels").model_copy(
                update={"source": SourcePlatform.TRUTH_SOCIAL}
            )
        )
        assert "this pipeline currently prefers false positives over false negatives" in prompt
        assert "return only the assets with a non-flat first-order directional view" in prompt
        assert "This post is a policy-expectations signal about crypto regulation and legislation." in prompt
    finally:
        asyncio.run(classifier.close())


def test_classifier_prompt_emphasizes_crypto_policy_direction_signals(settings) -> None:
    classifier = EventClassifier(settings.model_copy(update={"openai_api_key": SecretStr("test-key")}))
    try:
        prompt = classifier._prompt_for_post(  # noqa: SLF001
            post_with_text("loosening crypto policy").model_copy(update={"source": SourcePlatform.TRUTH_SOCIAL})
        )
        assert "This post is a policy-expectations signal about crypto regulation and legislation." in prompt
    finally:
        asyncio.run(classifier.close())


def test_classifier_recognizes_ultra_terse_market_signal_patterns() -> None:
    assert EventClassifier._ultra_terse_market_signal_label("Bitcoin") == "Bitcoin"  # noqa: SLF001
    assert EventClassifier._ultra_terse_market_signal_label("Oil") == "oil"  # noqa: SLF001
    assert EventClassifier._ultra_terse_market_signal_label("Tariffs") == "tariffs"  # noqa: SLF001
    assert EventClassifier._ultra_terse_market_signal_label("NVDA") == "NVIDIA / NVDA"  # noqa: SLF001
    assert EventClassifier._ultra_terse_market_signal_label("Tesla") == "Tesla / TSLA"  # noqa: SLF001
    assert EventClassifier._ultra_terse_market_signal_label("hello world") is None  # noqa: SLF001


def test_classifier_recognizes_policy_expectation_signal_patterns() -> None:
    assert EventClassifier._policy_expectations_signal_label("bitcoin and cryptocurrency legislation at both state and federal levels") == "crypto regulation and legislation"  # noqa: SLF001
    assert EventClassifier._policy_expectations_signal_label("loosening crypto policy") == "crypto regulation and legislation"  # noqa: SLF001
    assert EventClassifier._policy_expectations_signal_label("deregulatory moves on digital assets") == "crypto regulation and legislation"  # noqa: SLF001
    assert EventClassifier._policy_expectations_signal_label("expanding chip manufacturing subsidies") == "semiconductor and industrial policy"  # noqa: SLF001
    assert EventClassifier._policy_expectations_signal_label("generic political speech") is None  # noqa: SLF001

def test_classifier_schema_is_openai_strict() -> None:
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"].keys())
    breakdown_schema = SCHEMA["$defs"]["ScoringBreakdown"]
    assert breakdown_schema["additionalProperties"] is False
    assert set(breakdown_schema["required"]) == set(breakdown_schema["properties"].keys())
    impact_item_schema = SCHEMA["$defs"]["SparseMarketImpactItem"]
    assert impact_item_schema["additionalProperties"] is False
    assert set(impact_item_schema["required"]) == set(impact_item_schema["properties"].keys())


@pytest.mark.asyncio
async def test_telegram_relay_request_formatting(settings) -> None:
    relay = TelegramRelayClient(
        settings.model_copy(
            update={
                "alert_dry_run": False,
                "telegram_relay_api_key": SecretStr("relay-key"),
                "telegram_relay_chat_id": 12345,
            }
        )
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "relay-key"
        payload = json.loads(request.content.decode())
        assert payload["chat_id"] == 12345
        assert "parse_mode" not in payload
        assert "&nbsp;" not in payload["text"]
        assert " | " in payload["text"]
        return httpx.Response(200, json={"ok": True})

    relay._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://relay.local")
    result = await relay.send_alert(account=sample_account(), post=sample_post(), analysis=sample_analysis())
    await relay.close()
    assert result.status == "sent"


def test_format_alert_message_contains_summary() -> None:
    message = format_alert_message(account=sample_account(), post=sample_post(), analysis=sample_analysis())
    lines = message.splitlines()
    assert lines[0] == "@realDonaldTrump"
    assert lines[1] == "Major diplomatic development announced."
    assert lines[4] == "\U0001F534DXY  |  \U0001F7E2BTC  |  \U0001F7E2DOW/SPX/NDX"
    assert lines[5] == "\U0001F534OIL  |  \U0001F534METALS  |  \U0001F7E2INTC"
    assert lines[6] == "\U0001F7E2NVDA  |  \U0001F7E2AAPL  |  \U0001F7E2MSFT"
    assert lines[7] == "\U0001F7E2TSLA  |  \U0001F7E2ASML"


def test_format_alert_message_omits_flat_market_impacts() -> None:
    analysis = sample_analysis().model_copy(update={"market_impacts": MarketImpactSnapshot.flat(confidence=30)})
    message = format_alert_message(account=sample_account(), post=sample_post(), analysis=analysis)
    assert message.splitlines() == [
        "@realDonaldTrump",
        "Major diplomatic development announced.",
    ]
