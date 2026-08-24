from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from event_radar.models import AlertDecision, CanonicalPost, ScoringBreakdown


WEIGHTS = {
    "actor_importance": 20,
    "event_severity": 30,
    "immediacy": 20,
    "novelty": 15,
    "wider_impact": 15,
}


def compute_total_score(breakdown: ScoringBreakdown) -> float:
    weighted = (
        breakdown.actor_importance * WEIGHTS["actor_importance"]
        + breakdown.event_severity * WEIGHTS["event_severity"]
        + breakdown.immediacy * WEIGHTS["immediacy"]
        + breakdown.novelty * WEIGHTS["novelty"]
        + breakdown.wider_impact * WEIGHTS["wider_impact"]
    )
    return round(weighted / 100.0, 2)


def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=left.lower(), b=right.lower()).ratio()


@dataclass(slots=True)
class DuplicateCandidate:
    alert_id: int
    text: str
    total_score: float
    authority_rank: int


def dedupe_decision(
    post: CanonicalPost,
    score: float,
    authority_rank: int,
    candidates: list[DuplicateCandidate],
    *,
    threshold: float = 0.82,
    minimum_score_delta: int = 10,
) -> AlertDecision:
    for candidate in candidates:
        similarity = text_similarity(post.text, candidate.text)
        if similarity < threshold:
            continue
        if score >= candidate.total_score + minimum_score_delta:
            return AlertDecision(
                should_alert=True,
                reason="score_materially_higher_than_recent_duplicate",
                prior_alert_id=candidate.alert_id,
            )
        if authority_rank > candidate.authority_rank:
            return AlertDecision(
                should_alert=True,
                reason="more_authoritative_than_recent_duplicate",
                prior_alert_id=candidate.alert_id,
            )
        return AlertDecision(
            should_alert=False,
            reason="suppressed_recent_duplicate",
            prior_alert_id=candidate.alert_id,
        )
    return AlertDecision(should_alert=True, reason="no_recent_duplicate")

