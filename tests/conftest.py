from __future__ import annotations

from pathlib import Path

import pytest

from event_radar.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "event_radar.sqlite3",
        start_collectors=False,
        alert_dry_run=True,
        truth_social_cookie="session=test-cookie",
        x_bearer_token="test-token",
    )

