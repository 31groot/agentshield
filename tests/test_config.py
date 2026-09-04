from __future__ import annotations

import pytest

from config import ConfigurationError, Settings


def set_valid_environment(monkeypatch, tmp_path) -> None:
    #  Claude Configuration 
    # monkeypatch.setenv("LLM_PROVIDER", "claude")
    # monkeypatch.setenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
    # monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    # --- Groq Configuration ---
    monkeypatch.setenv(
        "LLM_PROVIDER",
        "groq",
    )
    monkeypatch.setenv(
        "GROQ_API_KEY",
        "test-groq-key",
    )
    monkeypatch.setenv(
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    )
    monkeypatch.setenv(
        "RAZORPAY_KEY_ID",
        "rzp_test",
    )
    monkeypatch.setenv(
        "RAZORPAY_KEY_SECRET",
        "test-secret",
    )
    monkeypatch.setenv(
        "MANDATE_SECRET_KEY",
        "x" * 32,
    )
    monkeypatch.setenv(
        "RAZORPAY_WEBHOOK_SECRET",
        "webhook-secret",
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
    monkeypatch.setenv(
        "DATABASE_PATH",
        str(tmp_path / "state"),
    )
    monkeypatch.setenv(
        "MANDATE_TTL_SECONDS",
        "300",
    )
    monkeypatch.setenv(
        "MAX_RETRIES",
        "3",
    )
    monkeypatch.setenv(
        "REQUEST_TIMEOUT_SECONDS",
        "10.0",
    )


def test_loads_valid_groq_configuration(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)

    settings = Settings.from_environment()

    #Claude assertions 
    # assert settings.llm_provider == "claude"
    # assert settings.claude_model == "claude-3-5-sonnet-20241022"
    # assert settings.anthropic_api_key == "test-anthropic-key"

    assert settings.llm_provider == "groq"
    assert settings.groq_api_key == "test-groq-key"
    assert settings.groq_model == "openai/gpt-oss-120b"
    assert settings.razorpay_key_id == "rzp_test"
    assert settings.razorpay_key_secret == "test-secret"
    assert settings.mandate_secret_key == b"x" * 32
    assert settings.database_path == str(tmp_path / "state")
    assert settings.mandate_ttl_seconds == 300
    assert settings.max_retries == 3
    assert settings.request_timeout_seconds == 10.0
    assert settings.webhook_secret == "webhook-secret"
    assert settings.api_token == "12345678901234567890123456789012"
    assert settings.api_user_id == "user_123"
    assert settings.api_agent_id == "agent_001"


#  Claude Specific Test Cases
# def test_loads_valid_claude_configuration(monkeypatch, tmp_path) -> None:
#     set_valid_environment(monkeypatch, tmp_path)
#     monkeypatch.setenv("LLM_PROVIDER", "claude")
#     monkeypatch.setenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
#     monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
#
#     settings = Settings.from_environment()
#     assert settings.llm_provider == "claude"
#     assert settings.claude_model == "claude-3-5-sonnet-20241022"
#     assert settings.anthropic_api_key == "test-anthropic-key"
#
# def test_rejects_missing_claude_model(monkeypatch, tmp_path) -> None:
#     set_valid_environment(monkeypatch, tmp_path)
#     monkeypatch.setenv("LLM_PROVIDER", "claude")
#     monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
#     monkeypatch.delenv("CLAUDE_MODEL", raising=False)
#
#     with pytest.raises(
#         ConfigurationError,
#         match="Missing required environment variable: CLAUDE_MODEL",
#     ):
#         Settings.from_environment()
#
# def test_rejects_missing_anthropic_api_key(monkeypatch, tmp_path) -> None:
#     set_valid_environment(monkeypatch, tmp_path)
#     monkeypatch.setenv("LLM_PROVIDER", "claude")
#     monkeypatch.setenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
#     monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
#
#     with pytest.raises(
#         ConfigurationError,
#         match="Missing required environment variable: ANTHROPIC_API_KEY",
#     ):
#         Settings.from_environment()



def test_rejects_missing_groq_api_key(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("GROQ_API_KEY")

    with pytest.raises(
        ConfigurationError,
        match="GROQ_API_KEY is required",
    ):
        Settings.from_environment()



def test_rejects_missing_groq_model(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("GROQ_MODEL")

    with pytest.raises(
        ConfigurationError,
        match="GROQ_MODEL is required",
    ):
        Settings.from_environment()


def test_rejects_missing_webhook_secret(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET")

    with pytest.raises(
        ConfigurationError,
        match="RAZORPAY_WEBHOOK_SECRET is required",
    ):
        Settings.from_environment()


def test_rejects_short_mandate_secret(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "MANDATE_SECRET_KEY",
        "short",
    )

    with pytest.raises(
        ConfigurationError,
        match="MANDATE_SECRET_KEY must be at least 32 bytes",
    ):
        Settings.from_environment()


def test_rejects_short_api_token(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "AGENTSHIELD_API_TOKEN",
        "too-short",
    )

    with pytest.raises(
        ConfigurationError,
        match="AGENTSHIELD_API_TOKEN must be at least 32 characters",
    ):
        Settings.from_environment()


def test_rejects_invalid_positive_integer(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "MAX_RETRIES",
        "0",
    )

    with pytest.raises(
        ConfigurationError,
        match="MAX_RETRIES must be greater than 0",
    ):
        Settings.from_environment()


def test_rejects_invalid_positive_float(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "REQUEST_TIMEOUT_SECONDS",
        "0",
    )

    with pytest.raises(
        ConfigurationError,
        match="REQUEST_TIMEOUT_SECONDS must be greater than 0",
    ):
        Settings.from_environment()


def test_defaults_provider_to_groq(monkeypatch, tmp_path) -> None:
    set_valid_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_PROVIDER")

    settings = Settings.from_environment()

    assert settings.llm_provider == "groq"