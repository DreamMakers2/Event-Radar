from __future__ import annotations

from datetime import UTC, datetime

from event_radar.models import CanonicalPost, ScoringBreakdown, SourcePlatform
from event_radar.scoring import DuplicateCandidate, compute_total_score, dedupe_decision


def test_compute_total_score_uses_weighted_breakdown() -> None:
    breakdown = ScoringBreakdown(
        actor_importance=100,
        event_severity=50,
        immediacy=75,
        novelty=25,
        wider_impact=50,
    )
    assert compute_total_score(breakdown) == 61.25


def test_dedupe_suppresses_recent_duplicate_without_material_change() -> None:
    post = CanonicalPost(
        source=SourcePlatform.X,
        account_db_id="acc",
        source_account_id="123",
        display_name="Test",
        handle="test",
        source_post_id="10",
        text="Breaking diplomatic talks resume in Geneva",
        published_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        raw_payload={},
    )
    decision = dedupe_decision(
        post,
        78.0,
        70,
        [DuplicateCandidate(alert_id=5, text="Breaking diplomatic talks resume in Geneva", total_score=76.0, authority_rank=70)],
    )
    assert not decision.should_alert
    assert decision.reason == "suppressed_recent_duplicate"


def test_dedupe_allows_more_authoritative_duplicate() -> None:
    post = CanonicalPost(
        source=SourcePlatform.X,
        account_db_id="acc",
        source_account_id="123",
        display_name="Test",
        handle="test",
        source_post_id="11",
        text="Major security cabinet statement released",
        published_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        raw_payload={},
    )
    decision = dedupe_decision(
        post,
        75.0,
        95,
        [DuplicateCandidate(alert_id=9, text="Major security cabinet statement released", total_score=74.0, authority_rank=75)],
    )
    assert decision.should_alert
    assert decision.reason == "more_authoritative_than_recent_duplicate"
