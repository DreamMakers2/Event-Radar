from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from event_radar.config import Settings
from event_radar.models import (
    AssetImpactPrediction,
    AccountConfig,
    AlertResult,
    AnalysisRecord,
    CanonicalPost,
    MarketImpactDirection,
    MarketImpactSnapshot,
)


class TelegramRelayClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(base_url=settings.telegram_relay_base_url, timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def send_alert(
        self,
        *,
        account: AccountConfig,
        post: CanonicalPost,
        analysis: AnalysisRecord,
        dry_run: bool | None = None,
    ) -> AlertResult:
        effective_dry_run = self.settings.alert_dry_run if dry_run is None else dry_run
        message = format_alert_message(account=account, post=post, analysis=analysis)
        if effective_dry_run:
            now = datetime.now(UTC)
            return AlertResult(status="dry_run", message_text=message, sent_at=now, acked_at=now)
        if not self.settings.telegram_relay_api_key or not self.settings.telegram_relay_chat_id:
            return AlertResult(
                status="suppressed",
                message_text=message,
                suppression_reason="telegram_relay_not_configured",
            )
        sent_at = datetime.now(UTC)
        response = await self._client.post(
            "/v1/messages",
            headers={"x-api-key": self.settings.telegram_relay_api_key.get_secret_value()},
            json={
                "chat_id": self.settings.telegram_relay_chat_id,
                "text": message[:4096],
                "disable_web_page_preview": True,
                "wait_seconds": 0,
            },
        )
        acked_at = datetime.now(UTC)
        response.raise_for_status()
        return AlertResult(
            status="sent",
            message_text=message,
            relay_response=response.json() if response.content else {},
            sent_at=sent_at,
            acked_at=acked_at,
        )


def format_alert_message(*, account: AccountConfig, post: CanonicalPost, analysis: AnalysisRecord) -> str:
    lines = [
        f"@{account.handle}",
        analysis.summary.strip(),
    ]
    impact_lines = format_market_impact_grid(analysis.market_impacts)
    if impact_lines:
        lines.extend(["", "", *impact_lines])
    return "\n".join(lines)


def format_market_impact_grid(market_impacts: MarketImpactSnapshot) -> list[str]:
    down_spx_ndx = _combine_predictions(
        market_impacts.dow,
        market_impacts.spx,
        market_impacts.ndx,
    )
    rows = [
        [
            ("DXY", market_impacts.dxy.direction),
            ("BTC", market_impacts.btc.direction),
            ("DOW/SPX/NDX", down_spx_ndx.direction),
        ],
        [
            ("OIL", market_impacts.oil.direction),
            ("METALS", market_impacts.metals.direction),
            ("INTC", market_impacts.intc.direction),
        ],
        [
            ("NVDA", market_impacts.nvda.direction),
            ("AAPL", market_impacts.aapl.direction),
            ("MSFT", market_impacts.msft.direction),
        ],
        [
            ("TSLA", market_impacts.tsla.direction),
            ("ASML", market_impacts.asml.direction),
            ("PLTR", market_impacts.pltr.direction),
        ],
    ]
    rendered_rows: list[str] = []
    for row in rows:
        visible_items = [
            _format_market_impact_item(label, direction)
            for label, direction in row
            if direction is not MarketImpactDirection.FLAT
        ]
        if visible_items:
            rendered_rows.append("  |  ".join(visible_items))
    return rendered_rows


def _combine_predictions(*predictions: AssetImpactPrediction) -> AssetImpactPrediction:
    weighted_score = 0
    total_confidence = 0
    for prediction in predictions:
        total_confidence += prediction.confidence
        if prediction.direction is MarketImpactDirection.UP:
            weighted_score += prediction.confidence
        elif prediction.direction is MarketImpactDirection.DOWN:
            weighted_score -= prediction.confidence
    if weighted_score > 0:
        direction = MarketImpactDirection.UP
    elif weighted_score < 0:
        direction = MarketImpactDirection.DOWN
    else:
        direction = MarketImpactDirection.FLAT
    confidence = round(total_confidence / max(len(predictions), 1))
    return AssetImpactPrediction(direction=direction, confidence=confidence)


def _format_market_impact_item(label: str, direction: MarketImpactDirection) -> str:
    return f"{_market_impact_emoji(direction)}{label}"


def _market_impact_emoji(direction: MarketImpactDirection) -> str:
    if direction is MarketImpactDirection.UP:
        return "\U0001F7E2"
    if direction is MarketImpactDirection.DOWN:
        return "\U0001F534"
    return "\u26AA"
