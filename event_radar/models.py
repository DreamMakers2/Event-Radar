from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourcePlatform(StrEnum):
    X = "x"
    TRUTH_SOCIAL = "truth_social"


class EventFeedbackVote(StrEnum):
    UP = "up"
    DOWN = "down"


class MarketImpactAsset(StrEnum):
    DXY = "dxy"
    BTC = "btc"
    DOW = "dow"
    SPX = "spx"
    NDX = "ndx"
    OIL = "oil"
    METALS = "metals"
    ENERGY = "energy"
    NVDA = "nvda"
    AAPL = "aapl"
    MSFT = "msft"
    TSLA = "tsla"
    INTC = "intc"
    ASML = "asml"
    PLTR = "pltr"


MARKET_IMPACT_FIELD_ORDER = (
    "dxy",
    "btc",
    "dow",
    "spx",
    "ndx",
    "oil",
    "metals",
    "energy",
    "nvda",
    "aapl",
    "msft",
    "tsla",
    "intc",
    "asml",
    "pltr",
)

MARKET_IMPACT_LABELS = {
    "dxy": "DXY",
    "btc": "BTC",
    "dow": "DOW",
    "spx": "SPX",
    "ndx": "NDX",
    "oil": "OIL",
    "metals": "METALS",
    "energy": "ENERGY",
    "nvda": "NVDA",
    "aapl": "AAPL",
    "msft": "MSFT",
    "tsla": "TSLA",
    "intc": "INTC",
    "asml": "ASML",
    "pltr": "PLTR",
}


class MarketImpactDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class AssetImpactPrediction(BaseModel):
    direction: MarketImpactDirection
    confidence: int = Field(ge=0, le=100)


class SparseMarketImpactItem(BaseModel):
    asset: MarketImpactAsset
    direction: MarketImpactDirection
    confidence: int = Field(ge=0, le=100)


class MarketImpactSnapshot(BaseModel):
    dxy: AssetImpactPrediction
    btc: AssetImpactPrediction
    dow: AssetImpactPrediction
    spx: AssetImpactPrediction
    ndx: AssetImpactPrediction
    oil: AssetImpactPrediction
    metals: AssetImpactPrediction
    energy: AssetImpactPrediction
    nvda: AssetImpactPrediction
    aapl: AssetImpactPrediction
    msft: AssetImpactPrediction
    tsla: AssetImpactPrediction
    intc: AssetImpactPrediction
    asml: AssetImpactPrediction
    pltr: AssetImpactPrediction

    @classmethod
    def flat(cls, *, confidence: int = 25) -> "MarketImpactSnapshot":
        return cls(
            **{
                field: AssetImpactPrediction(direction=MarketImpactDirection.FLAT, confidence=confidence)
                for field in MARKET_IMPACT_FIELD_ORDER
            }
        )

    def ordered_items(self) -> list[tuple[str, AssetImpactPrediction]]:
        return [(MARKET_IMPACT_LABELS[field], getattr(self, field)) for field in MARKET_IMPACT_FIELD_ORDER]

    @classmethod
    def from_sparse_items(
        cls,
        items: list[SparseMarketImpactItem],
        *,
        default_confidence: int = 25,
    ) -> "MarketImpactSnapshot":
        snapshot = cls.flat(confidence=default_confidence).model_dump(mode="python")
        seen_assets: set[str] = set()
        for item in items:
            asset_key = item.asset.value
            if asset_key in seen_assets:
                continue
            seen_assets.add(asset_key)
            snapshot[asset_key] = {
                "direction": item.direction,
                "confidence": item.confidence,
            }
        return cls.model_validate(snapshot)


class AccountConfig(BaseModel):
    id: str
    source: SourcePlatform
    entity_key: str
    display_name: str
    handle: str
    source_account_id: str | None = None
    source_url: str | None = None
    official: bool = True
    active: bool = True
    authority_rank: int = 50
    alert_threshold: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CanonicalPost(BaseModel):
    source: SourcePlatform
    account_db_id: str
    source_account_id: str
    display_name: str
    handle: str
    source_post_id: str
    canonical_url: str | None = None
    text: str
    links: list[str] = Field(default_factory=list)
    media_urls: list[str] = Field(default_factory=list)
    is_reply: bool = False
    is_repost: bool = False
    published_at: datetime
    observed_at: datetime
    raw_payload: dict[str, Any]
    collector_metadata: dict[str, Any] = Field(default_factory=dict)


class ScoringBreakdown(BaseModel):
    actor_importance: int = Field(ge=0, le=100)
    event_severity: int = Field(ge=0, le=100)
    immediacy: int = Field(ge=0, le=100)
    novelty: int = Field(ge=0, le=100)
    wider_impact: int = Field(ge=0, le=100)


class ClassifierOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    categories: list[str] = Field(default_factory=list, max_length=8)
    reasoning: str = Field(min_length=1, max_length=1200)
    breakdown: ScoringBreakdown
    market_impacts: MarketImpactSnapshot


class OpenAIClassifierOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    categories: list[str] = Field(default_factory=list, max_length=8)
    reasoning: str = Field(min_length=1, max_length=1200)
    breakdown: ScoringBreakdown
    market_impacts: list[SparseMarketImpactItem] = Field(default_factory=list, max_length=8)


class AnalysisRecord(BaseModel):
    normalized_post_id: int
    model: str
    summary: str
    categories: list[str]
    reasoning: str
    breakdown: ScoringBreakdown
    market_impacts: MarketImpactSnapshot
    total_score: float
    threshold: int
    decision: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    request_cost_usd: float = 0.0
    raw_response: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AlertDecision(BaseModel):
    should_alert: bool
    reason: str
    prior_alert_id: int | None = None


class AlertResult(BaseModel):
    status: str
    message_text: str
    suppression_reason: str | None = None
    relay_response: dict[str, Any] = Field(default_factory=dict)
    sent_at: datetime | None = None
    acked_at: datetime | None = None


class ConnectorStatus(BaseModel):
    name: str
    enabled: bool
    running: bool = False
    auth_configured: bool = False
    last_error: str | None = None
    last_success_at: datetime | None = None
    detail: str | None = None


class EventEnvelope(BaseModel):
    post: CanonicalPost
    analysis: AnalysisRecord
    alert: AlertResult | None = None


class ActivityRecord(BaseModel):
    id: int | None = None
    kind: str
    level: str
    component: str
    title: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AccountCreateRequest(BaseModel):
    source: SourcePlatform
    entity_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    handle: str = Field(min_length=1, max_length=80)
    source_account_id: str | None = Field(default=None, max_length=128)
    source_url: str | None = Field(default=None, max_length=512)
    official: bool = True
    active: bool = True
    authority_rank: int = Field(default=50, ge=0, le=100)
    alert_threshold: int | None = Field(default=None, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_key", "display_name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("must_not_be_blank")
        return normalized

    @field_validator("handle", mode="before")
    @classmethod
    def normalize_handle(cls, value: Any) -> str:
        normalized = str(value or "").strip().lstrip("@").lower()
        if not normalized:
            raise ValueError("must_not_be_blank")
        return normalized

    @field_validator("source_account_id", "source_url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class AccountUpdateRequest(BaseModel):
    active: bool | None = None
    alert_threshold: int | None = Field(default=None, ge=0, le=100)
    source_account_id: str | None = None
    authority_rank: int | None = Field(default=None, ge=0, le=100)
    metadata: dict[str, Any] | None = None


class EventVoteRequest(BaseModel):
    vote: EventFeedbackVote | None


class EventVoteRecord(BaseModel):
    normalized_post_id: int
    vote: EventFeedbackVote | None
    updated_at: datetime


class ManualEventTestRequest(BaseModel):
    handle: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("handle", mode="before")
    @classmethod
    def normalize_test_handle(cls, value: Any) -> str:
        normalized = str(value or "").strip().lstrip("@").lower()
        if not normalized:
            raise ValueError("must_not_be_blank")
        return normalized

    @field_validator("message", mode="before")
    @classmethod
    def normalize_test_message(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("must_not_be_blank")
        return normalized


class ManualEventTestAccount(BaseModel):
    id: str
    source: SourcePlatform
    display_name: str
    handle: str
    authority_rank: int
    alert_threshold: int | None = None
    active: bool


class ManualEventTestAnalysis(BaseModel):
    mode: str
    summary: str
    categories: list[str]
    reasoning: str
    breakdown: ScoringBreakdown
    market_impacts: MarketImpactSnapshot
    total_score: float
    threshold: int
    decision: str
    request_cost_usd: float


class ManualEventTestOutcome(BaseModel):
    would_notify: bool
    status: str
    reason: str | None = None
    message_text: str


class ManualEventTestResponse(BaseModel):
    account: ManualEventTestAccount
    analysis: ManualEventTestAnalysis
    outcome: ManualEventTestOutcome
