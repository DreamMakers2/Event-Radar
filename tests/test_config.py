from __future__ import annotations

from pathlib import Path

from event_radar.config import Settings, get_settings


def test_settings_parse_shell_env_with_invalid_telegram_names(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "env.sh"
    env_file.write_text(
        "\n".join(
            [
                "export OPENAI_API_KEY='openai-key'",
                "export TELEGRAM-RELAY-API-KEY='relay-key'",
                "export TELEGRAM-RELAY-CHAT-ID='12345'",
                "export X_API-BEARER_TOKEN='bearer-key'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("EVENT_RADAR_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EVENT_RADAR_TELEGRAM_RELAY_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_RELAY_API_KEY", raising=False)
    monkeypatch.delenv("EVENT_RADAR_TELEGRAM_RELAY_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_RELAY_CHAT_ID", raising=False)
    monkeypatch.delenv("EVENT_RADAR_X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("EVENT_RADAR_X_API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("EVENT_RADAR_ENV_FILE", str(env_file))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.openai_api_key.get_secret_value() == "openai-key"
    assert settings.telegram_relay_api_key.get_secret_value() == "relay-key"
    assert settings.telegram_relay_chat_id == 12345
    assert settings.x_bearer_token.get_secret_value() == "bearer-key"
    get_settings.cache_clear()


def test_settings_default_threshold_and_output_estimate() -> None:
    settings = Settings()
    assert settings.alert_threshold == 65
    assert settings.estimated_output_tokens_per_post == 120
    assert settings.openai_usage_project_name == "Event Radar"
    assert settings.openai_usage_api_key_name == "Event Radar"
