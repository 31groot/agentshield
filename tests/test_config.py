import pytest

from config import ConfigurationError, Settings


def _valid_environment(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "test-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "test-key-id")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test-key-secret")
    monkeypatch.setenv(
        "RAZORPAY_WEBHOOK_SECRET",
        "test-webhook-secret",
    )
    monkeypatch.setenv(
        "MANDATE_SECRET_KEY",
        "12345678901234567890123456789012",
    )
    monkeypatch.setenv(
        "AGENTSHIELD_API_TOKEN",
        "12345678901234567890123456789012",
    )
    monkeypatch.setenv(
        "AGENTSHIELD_API_USER_ID",
        "user_123",
    )
    monkeypatch.setenv(
        "AGENTSHIELD_API_AGENT_ID",
        "agent_001",
    )


def test_settings_load_from_environment(monkeypatch):
    _valid_environment(monkeypatch)

    settings = Settings.from_environment()

    assert settings.claude_model == "test-model"
    assert settings.anthropic_api_key == "test-anthropic-key"
    assert settings.razorpay_key_id == "test-key-id"
    assert settings.razorpay_key_secret == "test-key-secret"
    assert settings.webhook_secret == "test-webhook-secret"
    assert settings.mandate_secret_key == (
        b"12345678901234567890123456789012"
    )
    assert settings.database_path == "state.db"
    assert settings.mandate_ttl_seconds == 300
    assert settings.max_retries == 3
    assert settings.request_timeout_seconds == 10.0
    assert settings.api_token == (
        "12345678901234567890123456789012"
    )
    assert settings.api_user_id == "user_123"
    assert settings.api_agent_id == "agent_001"

def test_missing_required_configuration_fails(monkeypatch):
    _valid_environment(monkeypatch)
    monkeypatch.delenv("CLAUDE_MODEL")

    with pytest.raises(ConfigurationError):
        Settings.from_environment()


def test_short_mandate_secret_fails(monkeypatch):
    _valid_environment(monkeypatch)
    monkeypatch.setenv("MANDATE_SECRET_KEY", "too-short")

    with pytest.raises(
        ConfigurationError,
        match="at least 32 bytes",
    ):
        Settings.from_environment()


def test_invalid_retry_count_fails(monkeypatch):
    _valid_environment(monkeypatch)
    monkeypatch.setenv("MAX_RETRIES", "0")

    with pytest.raises(
        ConfigurationError,
        match="MAX_RETRIES",
    ):
        Settings.from_environment()


def test_invalid_timeout_fails(monkeypatch):
    _valid_environment(monkeypatch)
    monkeypatch.setenv(
        "REQUEST_TIMEOUT_SECONDS",
        "not-a-number",
    )

    with pytest.raises(
        ConfigurationError,
        match="REQUEST_TIMEOUT_SECONDS",
    ):
        Settings.from_environment()
