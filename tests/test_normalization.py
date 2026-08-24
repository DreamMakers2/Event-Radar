from __future__ import annotations

from datetime import UTC, datetime

from event_radar.connectors.truth_social import TruthSocialConnector
from event_radar.connectors.x import XConnector
from event_radar.db import Repository
from event_radar.models import AccountConfig, SourcePlatform


def make_account(source: SourcePlatform) -> AccountConfig:
    return AccountConfig(
        id=f"{source.value}_acc",
        source=source,
        entity_key="entity",
        display_name="Display",
        handle="handle",
        source_account_id="42",
        source_url=None,
        official=True,
        active=True,
        authority_rank=80,
        alert_threshold=None,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_x_normalization_extracts_reply_and_links(settings) -> None:
    connector = XConnector(settings=settings, repository=Repository(settings.database_path), on_post=None)  # type: ignore[arg-type]
    account = make_account(SourcePlatform.X)
    post = connector.normalize_tweet_payload(
        {
            "id": "100",
            "author_id": "42",
            "text": "Statement https://t.co/example",
            "created_at": "2026-03-26T00:00:00Z",
            "entities": {"urls": [{"expanded_url": "https://example.com"}]},
            "referenced_tweets": [{"type": "replied_to", "id": "55"}],
            "attachments": {"media_keys": ["m1"]},
        },
        account,
        {"m1": {"media_key": "m1", "url": "https://img.example.com/media.jpg"}},
    )
    assert post.is_reply is True
    assert post.links == ["https://example.com"]
    assert post.media_urls == ["https://img.example.com/media.jpg"]


def test_truth_social_normalization_strips_html(settings) -> None:
    connector = TruthSocialConnector(settings=settings, repository=Repository(settings.database_path), on_post=None)  # type: ignore[arg-type]
    account = make_account(SourcePlatform.TRUTH_SOCIAL)
    post = connector.normalize_status_payload(
        {
            "id": "900",
            "created_at": "2026-03-26T00:00:00Z",
            "content": "<p>New <strong>statement</strong> issued</p>",
            "spoiler_text": "",
            "url": "https://truthsocial.com/@handle/900",
            "in_reply_to_id": None,
            "reblog": None,
            "media_attachments": [{"url": "https://cdn.truth/media.jpg"}],
        },
        account,
    )
    assert post.text == "New statement issued"
    assert post.media_urls == ["https://cdn.truth/media.jpg"]
    assert post.canonical_url == "https://truthsocial.com/@handle/900"

