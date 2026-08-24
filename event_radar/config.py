from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr

from event_radar.utils import (
    ensure_directory,
    env_lookup,
    getenv,
    parse_bool,
    parse_float,
    parse_int,
    parse_shell_exports,
)


DEFAULT_ENV_FILE = Path("config/env.sh")


class Settings(BaseModel):
    app_host: str = "127.0.0.1"
    app_port: int = 8089
    database_path: Path = Path("var/event_radar.db")
    log_level: str = "INFO"

    env_file: Path = DEFAULT_ENV_FILE

    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_admin_key: SecretStr | None = None
    openai_model: str = "gpt-5-mini"
    openai_usage_project_name: str = "Event Radar"
    openai_usage_api_key_name: str = "Event Radar"
    openai_timeout_seconds: float = 15.0
    openai_reasoning_effort: str = "low"
    openai_input_cost_per_million_usd: float = 0.25
    openai_output_cost_per_million_usd: float = 2.0
    openai_cached_input_cost_per_million_usd: float = 0.025
    estimated_input_tokens_per_post: int = 550
    estimated_output_tokens_per_post: int = 120
    estimated_posts_per_day: int = 75
    eur_per_usd_default: float = 0.8666

    telegram_relay_base_url: str = "http://127.0.0.1:8080"
    telegram_relay_api_key: SecretStr | None = None
    telegram_relay_chat_id: int | None = None
    telegram_relay_test_chat_id: int | None = None
    alert_dry_run: bool = False

    x_api_base_url: str = "https://api.x.com"
    x_bearer_token: SecretStr | None = None
    x_stream_enabled: bool = True
    x_backfill_poll_seconds: float = 20.0
    x_rule_sync_seconds: float = 60.0

    truth_social_base_url: str = "https://truthsocial.com"
    truth_social_cookie_file: Path | None = None
    truth_social_cookie: SecretStr | None = None
    truth_social_poll_seconds: float = 3.0

    alert_threshold: int = 65
    duplicate_window_minutes: int = 30
    duplicate_score_delta: int = 10
    historical_backfill_alert_minutes: int = 0
    start_collectors: bool = True

    @property
    def monitoring_enabled(self) -> bool:
        return self.start_collectors

    @property
    def effective_database_path(self) -> Path:
        ensure_directory(self.database_path.parent)
        return self.database_path


def _build_settings_data() -> dict[str, Any]:
    env = getenv()
    env_file = Path(env.get("EVENT_RADAR_ENV_FILE", DEFAULT_ENV_FILE))
    shell_env = parse_shell_exports(env_file)
    merged = {**env, **shell_env}
    return {
        "app_host": env_lookup(merged, "EVENT_RADAR_APP_HOST") or "127.0.0.1",
        "app_port": parse_int(env_lookup(merged, "EVENT_RADAR_APP_PORT"), 8089),
        "database_path": Path(env_lookup(merged, "EVENT_RADAR_DATABASE_PATH") or "var/event_radar.db"),
        "log_level": env_lookup(merged, "EVENT_RADAR_LOG_LEVEL") or "INFO",
        "env_file": env_file,
        "openai_api_key": env_lookup(merged, "EVENT_RADAR_OPENAI_API_KEY", "OPENAI_API_KEY"),
        "openai_base_url": env_lookup(merged, "EVENT_RADAR_OPENAI_BASE_URL") or "https://api.openai.com/v1",
        "openai_admin_key": env_lookup(merged, "EVENT_RADAR_OPENAI_ADMIN_KEY", "OPENAI_ADMIN_KEY"),
        "openai_model": env_lookup(merged, "EVENT_RADAR_OPENAI_MODEL") or "gpt-5-mini",
        "openai_usage_project_name": env_lookup(merged, "EVENT_RADAR_OPENAI_USAGE_PROJECT_NAME") or "Event Radar",
        "openai_usage_api_key_name": env_lookup(merged, "EVENT_RADAR_OPENAI_USAGE_API_KEY_NAME") or "Event Radar",
        "openai_timeout_seconds": parse_float(env_lookup(merged, "EVENT_RADAR_OPENAI_TIMEOUT_SECONDS"), 15.0),
        "openai_reasoning_effort": env_lookup(merged, "EVENT_RADAR_OPENAI_REASONING_EFFORT") or "low",
        "openai_input_cost_per_million_usd": parse_float(
            env_lookup(merged, "EVENT_RADAR_OPENAI_INPUT_COST_PER_MILLION_USD"),
            0.25,
        ),
        "openai_output_cost_per_million_usd": parse_float(
            env_lookup(merged, "EVENT_RADAR_OPENAI_OUTPUT_COST_PER_MILLION_USD"),
            2.0,
        ),
        "openai_cached_input_cost_per_million_usd": parse_float(
            env_lookup(merged, "EVENT_RADAR_OPENAI_CACHED_INPUT_COST_PER_MILLION_USD"),
            0.025,
        ),
        "estimated_input_tokens_per_post": parse_int(
            env_lookup(merged, "EVENT_RADAR_ESTIMATED_INPUT_TOKENS_PER_POST"),
            550,
        ),
        "estimated_output_tokens_per_post": parse_int(
            env_lookup(merged, "EVENT_RADAR_ESTIMATED_OUTPUT_TOKENS_PER_POST"),
            120,
        ),
        "estimated_posts_per_day": parse_int(env_lookup(merged, "EVENT_RADAR_ESTIMATED_POSTS_PER_DAY"), 75),
        "eur_per_usd_default": parse_float(env_lookup(merged, "EVENT_RADAR_EUR_PER_USD_DEFAULT"), 0.8666),
        "telegram_relay_base_url": env_lookup(merged, "EVENT_RADAR_TELEGRAM_RELAY_BASE_URL")
        or "http://127.0.0.1:8080",
        "telegram_relay_api_key": env_lookup(
            merged,
            "EVENT_RADAR_TELEGRAM_RELAY_API_KEY",
            "TELEGRAM_RELAY_API_KEY",
            "TELEGRAM-RELAY-API-KEY",
        ),
        "telegram_relay_chat_id": parse_int(
            env_lookup(
                merged,
                "EVENT_RADAR_TELEGRAM_RELAY_CHAT_ID",
                "TELEGRAM_RELAY_CHAT_ID",
                "TELEGRAM-RELAY-CHAT-ID",
            )
        ),
        "telegram_relay_test_chat_id": parse_int(
            env_lookup(merged, "EVENT_RADAR_TELEGRAM_RELAY_TEST_CHAT_ID", "TELEGRAM_RELAY_TEST_CHAT_ID")
        ),
        "alert_dry_run": parse_bool(env_lookup(merged, "EVENT_RADAR_ALERT_DRY_RUN"), False),
        "x_api_base_url": env_lookup(merged, "EVENT_RADAR_X_API_BASE_URL") or "https://api.x.com",
        "x_bearer_token": env_lookup(
            merged,
            "EVENT_RADAR_X_BEARER_TOKEN",
            "EVENT_RADAR_X_API_BEARER_TOKEN",
            "X_BEARER_TOKEN",
            "X_API_BEARER_TOKEN",
            "X_API-BEARER_TOKEN",
        ),
        "x_stream_enabled": parse_bool(env_lookup(merged, "EVENT_RADAR_X_STREAM_ENABLED"), True),
        "x_backfill_poll_seconds": parse_float(env_lookup(merged, "EVENT_RADAR_X_BACKFILL_POLL_SECONDS"), 20.0),
        "x_rule_sync_seconds": parse_float(env_lookup(merged, "EVENT_RADAR_X_RULE_SYNC_SECONDS"), 60.0),
        "truth_social_base_url": env_lookup(merged, "EVENT_RADAR_TRUTH_SOCIAL_BASE_URL") or "https://truthsocial.com",
        "truth_social_cookie_file": Path(env_lookup(merged, "EVENT_RADAR_TRUTH_SOCIAL_COOKIE_FILE", "TRUTH_SOCIAL_COOKIE_FILE"))
        if env_lookup(merged, "EVENT_RADAR_TRUTH_SOCIAL_COOKIE_FILE", "TRUTH_SOCIAL_COOKIE_FILE")
        else None,
        "truth_social_cookie": env_lookup(merged, "EVENT_RADAR_TRUTH_SOCIAL_COOKIE", "TRUTH_SOCIAL_COOKIE"),
        "truth_social_poll_seconds": parse_float(
            env_lookup(merged, "EVENT_RADAR_TRUTH_SOCIAL_POLL_SECONDS"),
            3.0,
        ),
        "alert_threshold": parse_int(env_lookup(merged, "EVENT_RADAR_ALERT_THRESHOLD"), 65),
        "duplicate_window_minutes": parse_int(env_lookup(merged, "EVENT_RADAR_DUPLICATE_WINDOW_MINUTES"), 30),
        "duplicate_score_delta": parse_int(env_lookup(merged, "EVENT_RADAR_DUPLICATE_SCORE_DELTA"), 10),
        "historical_backfill_alert_minutes": parse_int(
            env_lookup(merged, "EVENT_RADAR_HISTORICAL_BACKFILL_ALERT_MINUTES"),
            0,
        ),
        "start_collectors": parse_bool(env_lookup(merged, "EVENT_RADAR_START_COLLECTORS"), True),
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.model_validate(_build_settings_data())
