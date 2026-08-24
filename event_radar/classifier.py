from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from event_radar.config import Settings
from event_radar.models import CanonicalPost, ClassifierOutput, MarketImpactSnapshot, OpenAIClassifierOutput
from event_radar.scoring import compute_total_score
from event_radar.utils import unique_preserve_order


LOGGER = logging.getLogger(__name__)


class ClassificationUnavailableError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _to_openai_strict_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_to_openai_strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: _to_openai_strict_schema(item) for key, item in value.items()}
    if normalized.get("type") == "object" or "properties" in normalized:
        normalized["additionalProperties"] = False
        properties = normalized.get("properties", {})
        if isinstance(properties, dict):
            normalized["required"] = list(properties.keys())
    return normalized


SCHEMA = _to_openai_strict_schema(OpenAIClassifierOutput.model_json_schema())


class EventClassifier:
    _DEFAULT_MAX_OUTPUT_TOKENS = 700
    _RETRY_MAX_OUTPUT_TOKENS = 1400
    _ULTRA_TERSE_SIGNAL_LABELS = {
        "bitcoin": "Bitcoin",
        "btc": "Bitcoin",
        "$btc": "Bitcoin",
        "crypto": "crypto",
        "cryptocurrency": "crypto",
        "oil": "oil",
        "crude": "oil",
        "gold": "gold",
        "silver": "silver",
        "dxy": "the US dollar",
        "dollar": "the US dollar",
        "dow": "the Dow",
        "spx": "the S&P 500",
        "s&p": "the S&P 500",
        "ndx": "the Nasdaq 100",
        "nasdaq": "the Nasdaq",
        "tariff": "tariffs",
        "tariffs": "tariffs",
        "rate": "rates",
        "rates": "rates",
        "fed": "the Federal Reserve",
        "sanction": "sanctions",
        "sanctions": "sanctions",
        "chip": "chips",
        "chips": "chips",
        "semiconductor": "semiconductors",
        "semiconductors": "semiconductors",
        "nvda": "NVIDIA / NVDA",
        "nvidia": "NVIDIA / NVDA",
        "aapl": "Apple / AAPL",
        "apple": "Apple / AAPL",
        "msft": "Microsoft / MSFT",
        "microsoft": "Microsoft / MSFT",
        "tsla": "Tesla / TSLA",
        "tesla": "Tesla / TSLA",
        "intc": "Intel / INTC",
        "intel": "Intel / INTC",
        "asml": "ASML",
        "pltr": "Palantir / PLTR",
        "palantir": "Palantir / PLTR",
    }
    _CRYPTO_SIGNAL_TERMS = ("bitcoin", "btc", "crypto", "cryptocurrency", "digital asset", "digital assets", "stablecoin")
    _SEMICONDUCTOR_SIGNAL_TERMS = (
        "chip",
        "chips",
        "semiconductor",
        "semiconductors",
        "chip manufacturing",
        "semiconductor manufacturing",
        "foundry",
        "asml",
        "nvda",
        "nvidia",
        "intc",
        "intel",
    )
    _TRADE_POLICY_SIGNAL_TERMS = (
        "tariff",
        "tariffs",
        "sanction",
        "sanctions",
        "export control",
        "export controls",
        "procurement",
        "subsidy",
        "subsidies",
        "tax credit",
        "tax credits",
        "manufacturing",
    )
    _POLICY_SIGNAL_TERMS = (
        "policy",
        "policies",
        "legislation",
        "regulation",
        "regulatory",
        "deregulation",
        "deregulatory",
        "oversight",
        "guidance",
        "friendlier",
        "friendlier rules",
        "lighter oversight",
        "lighter regulation",
        "loosening",
        "loosen",
        "easing",
        "support",
        "support for",
        "bill",
        "law",
        "laws",
        "federal",
        "state",
        "states",
        "executive order",
        "approve",
        "approval",
        "ban",
        "ban on",
        "framework",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def analyze(self, post: CanonicalPost) -> tuple[ClassifierOutput, float, dict[str, Any]]:
        if not self.settings.openai_api_key:
            raise ClassificationUnavailableError(
                "missing_openai_api_key",
                "OpenAI classification is required, but no OPENAI_API_KEY is configured.",
            )
        try:
            return await self._analyze_with_retry(post)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("OpenAI classification failed")
            raise ClassificationUnavailableError("openai_classification_failed", str(exc)) from exc

    async def _analyze_with_retry(self, post: CanonicalPost) -> tuple[ClassifierOutput, float, dict[str, Any]]:
        output_budgets = [self._DEFAULT_MAX_OUTPUT_TOKENS, self._RETRY_MAX_OUTPUT_TOKENS]
        last_error: Exception | None = None
        for attempt_index, max_output_tokens in enumerate(output_budgets, start=1):
            raw = await self._request_analysis(post, max_output_tokens=max_output_tokens)
            try:
                parsed = self._parse_classifier_output(raw)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                has_retry_remaining = attempt_index < len(output_budgets)
                if has_retry_remaining and self._should_retry_incomplete_output(raw, exc):
                    LOGGER.warning(
                        "OpenAI classification returned incomplete JSON on attempt %s, retrying with max_output_tokens=%s",
                        attempt_index,
                        output_budgets[attempt_index],
                    )
                    continue
                raise
            raw_with_mode = dict(raw)
            raw_with_mode["mode"] = "model"
            return parsed, compute_total_score(parsed.breakdown), raw_with_mode
        assert last_error is not None
        raise last_error

    async def _request_analysis(self, post: CanonicalPost, *, max_output_tokens: int) -> dict[str, Any]:
        payload = {
            "model": self.settings.openai_model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You classify high-impact political and geopolitical social posts for a real-time alerting system. "
                                "Return strict JSON only. Use the rubric as written, keep the output concise, and prefer recall over precision when the market relevance is plausible."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._prompt_for_post(post),
                        }
                    ],
                },
            ],
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": self.settings.openai_reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "event_radar_analysis",
                    "strict": True,
                    "schema": SCHEMA,
                }
            },
        }
        response = await self._client.post(
            "/responses",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.is_error:
            try:
                error_body = response.json()
            except Exception:  # noqa: BLE001
                error_body = response.text
            raise httpx.HTTPStatusError(
                f"{response.status_code} error from Responses API: {error_body}",
                request=response.request,
                response=response,
            )
        return response.json()

    def _parse_classifier_output(self, raw: dict[str, Any]) -> ClassifierOutput:
        text = self._extract_output_text(raw)
        parsed = OpenAIClassifierOutput.model_validate_json(text)
        return ClassifierOutput(
            summary=parsed.summary,
            categories=unique_preserve_order(parsed.categories),
            reasoning=parsed.reasoning,
            breakdown=parsed.breakdown,
            market_impacts=MarketImpactSnapshot.from_sparse_items(parsed.market_impacts),
        )

    @staticmethod
    def _should_retry_incomplete_output(raw: dict[str, Any], exc: Exception) -> bool:
        incomplete_reason = (raw.get("incomplete_details") or {}).get("reason")
        if raw.get("status") == "incomplete" or incomplete_reason == "max_output_tokens":
            return True
        error_text = str(exc).lower()
        if "eof while parsing" in error_text or "unterminated string" in error_text:
            return True
        output_text = raw.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return not output_text.rstrip().endswith("}")
        return False

    def _prompt_for_post(self, post: CanonicalPost) -> str:
        extra_guidance = self._dynamic_prompt_guidance(post)
        return (
            "Analyze this newly observed post for an alerting pipeline.\n\n"
            "Rubric dimensions, each 0-100: actor_importance, event_severity, immediacy, novelty, wider_impact.\n"
            "Use broad but useful categories such as diplomacy, military, domestic_politics, sanctions, protest, economy, energy, cyber, or media.\n"
            "Summary should be one or two short sentences.\n"
            "Reasoning should stay under 120 words.\n\n"
            "Classification stance: this pipeline currently prefers false positives over false negatives.\n"
            "If a post could plausibly move a tradeable asset, sector, macro expectation, policy probability, or geopolitical risk narrative within 1-24 hours, lean toward scoring it as material instead of dismissing it.\n"
            "Do not require confirmation, implementation detail, or multiple supporting facts when the actor and headline alone can trigger repricing.\n"
            "Reserve genuinely low scores for clearly generic, ceremonial, personal, or otherwise non-actionable posts.\n"
            "Avoid compressing plausible market signals into middling scores just because the text is brief, noisy, or politically framed.\n\n"
            "Also produce a market-impact view for the next 1-24 hours if the post is credible and taken seriously by markets.\n"
            "For market_impacts, return only the assets with a non-flat first-order directional view. Omit everything else entirely; omitted assets will be treated as flat internally.\n"
            "Use direction up or down for included assets. Positive means the asset price likely rises; negative means it likely falls.\n"
            "Asset meanings: dxy=US Dollar Index, btc=Bitcoin, dow=Dow Jones Industrial Average, spx=S&P 500, ndx=Nasdaq 100,\n"
            "oil=crude oil, metals=liquid metals basket proxy, energy=listed energy equities, and nvda/aapl/msft/tsla/intc/asml/pltr are single-name equities.\n"
            "Keep confidence realistic and include only the most directly affected assets.\n\n"
            "Important scoring guidance: terse principal-actor claims about troop presence, invasion preparation, ground operations, intervention, or other military escalation in live hotspot theaters\n"
            "can still be highly material even when unsourced. Do not over-discount them purely for brevity or low verification if the speaker is a market-moving political principal.\n\n"
            "Core calibration principle: this system is trying to catch posts that can move markets or policy expectations in the next 1-24 hours. The post itself can be the catalyst.\n"
            "Do not require enacted policy, confirmed military action, or detailed evidence if the headline alone can plausibly reprice assets, sectors, or geopolitical risk.\n"
            "If traders, desks, or policymakers would react to the post as a live signal, keep event_severity, immediacy, and wider_impact meaningfully elevated.\n\n"
            "When uncertain between borderline and material for a high-authority actor discussing war, sanctions, energy, central-bank direction, tariffs, chips, industrial policy, crypto, or a directly tradeable asset,\n"
            "bias toward the material interpretation unless the text is plainly unserious or obviously unrelated to markets.\n\n"
            "Likewise, terse principal-actor signals about semiconductor capacity, domestic manufacturing expansion, tariffs, subsidies, procurement, strategic-industry policy,\n"
            "or crypto / digital-asset legislation can be highly market-moving even when details are sparse. Do not dismiss them as generic rhetoric if they plausibly shift expectations\n"
            "for chipmakers, industrials, Bitcoin, or policy-sensitive equities.\n\n"
            "Also treat a single-word or ultra-terse mention of a directly tradeable asset, sector, or macro policy lever from a market-moving political principal as potentially material.\n"
            "Examples include posts like 'Bitcoin', 'Oil', 'Gold', 'Tariffs', 'Chips', 'NVDA', or 'Tesla'. The lack of detail does not make them unimportant: the post itself can function as an endorsement,\n"
            "agenda-setting signal, or cue about imminent attention, and markets can react immediately. For these cases, do not default to very low event_severity, immediacy, or wider_impact\n"
            "solely because the text is short. Novelty should reflect market surprise and signal value, not just word count.\n\n"
            "Benchmark: if a former president or comparable principal posts only 'Bitcoin', that is usually not a trivial 0-40 event for alerting purposes unless there is a clear reason\n"
            "markets would ignore it. BTC, crypto proxies, and policy-sensitive tech names can react immediately to that kind of direct attention signal.\n\n"
            f"{extra_guidance}"
            f"Source: {post.source.value}\n"
            f"Actor: {post.display_name} (@{post.handle})\n"
            f"Published at: {post.published_at.isoformat()}\n"
            f"Observed at: {post.observed_at.isoformat()}\n"
            f"Reply: {post.is_reply}\n"
            f"Repost: {post.is_repost}\n"
            f"URL: {post.canonical_url or 'n/a'}\n"
            f"Text:\n{post.text}\n"
        )

    def _dynamic_prompt_guidance(self, post: CanonicalPost) -> str:
        guidance_blocks: list[str] = []
        signal_label = self._ultra_terse_market_signal_label(post.text)
        if signal_label is not None:
            guidance_blocks.append(
                f"This post is an ultra-terse direct market signal about {signal_label}. Treat it as the speaker choosing to spotlight a tradeable asset, sector, or policy lever itself.\n"
                "For a market-moving principal, this often produces immediate attention and repricing in the named asset and linked proxies even without additional explanation.\n"
                "Unless there is a concrete reason markets would ignore the post, avoid trivial scoring. As a calibration point, event_severity should usually land around 65-80,\n"
                "immediacy around 75-90, and wider_impact around 60-80 for this pattern, with novelty reflecting surprise and signal value rather than word count.\n"
            )

        policy_label = self._policy_expectations_signal_label(post.text)
        if policy_label is not None:
            guidance_blocks.append(
                f"This post is a policy-expectations signal about {policy_label}. The relevant event is the shift in expected policy probability, not enacted implementation.\n"
                "Markets can reprice immediately on the headline, even before bill text, formal votes, or signed orders exist.\n"
                "Do not under-score it merely because the post is short or lacks implementation detail. Severity and wider impact should reflect plausible repricing in the directly affected assets,\n"
                "sectors, and policy-sensitive equities over the next 1-24 hours.\n"
            )

        if not guidance_blocks:
            return ""
        return "\n".join(guidance_blocks) + "\n"

    @classmethod
    def _ultra_terse_market_signal_label(cls, text: str) -> str | None:
        tokens = re.findall(r"[$A-Za-z0-9]+", text.lower())
        if not tokens or len(tokens) > 3:
            return None
        if len(tokens) == 1:
            return cls._ULTRA_TERSE_SIGNAL_LABELS.get(tokens[0])
        joined = " ".join(tokens)
        return cls._ULTRA_TERSE_SIGNAL_LABELS.get(joined)

    @classmethod
    def _policy_expectations_signal_label(cls, text: str) -> str | None:
        normalized = re.sub(r"[^a-z0-9$ ]+", " ", text.lower())
        has_policy_term = any(term in normalized for term in cls._POLICY_SIGNAL_TERMS) or any(
            term in normalized for term in cls._TRADE_POLICY_SIGNAL_TERMS
        )
        if not has_policy_term:
            return None
        if any(term in normalized for term in cls._CRYPTO_SIGNAL_TERMS):
            return "crypto regulation and legislation"
        if any(term in normalized for term in cls._SEMICONDUCTOR_SIGNAL_TERMS):
            return "semiconductor and industrial policy"
        if any(term in normalized for term in cls._TRADE_POLICY_SIGNAL_TERMS):
            return "trade, tariff, sanctions, or industrial policy"
        return "market-sensitive public policy"

    @staticmethod
    def _extract_output_text(raw: dict[str, Any]) -> str:
        if isinstance(raw.get("output_text"), str) and raw["output_text"].strip():
            return raw["output_text"]
        output = raw.get("output", [])
        chunks: list[str] = []
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text)
        if not chunks:
            raise ValueError(f"No structured output text found in response: {json.dumps(raw)[:500]}")
        return "\n".join(chunks)
def extract_usage(raw: dict[str, Any]) -> dict[str, int]:
    usage = raw.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    cached_input_tokens = int(
        usage.get("input_cached_tokens")
        or usage.get("prompt_tokens_cached")
        or (usage.get("input_tokens_details") or {}).get("cached_tokens")
        or 0
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
    }
