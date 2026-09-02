from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from application.container import (
    ApplicationContainer,
    FailClosedAuthorizationProvider,
)
from config import Settings
from models.authorization import AuthorizationDecision


class DummyAuthorization:
    def __call__(self, analysis):
        return AuthorizationDecision(
            allowed=True,
            reason="TEST_APPROVED",
            authorization_id="test-auth",
        )


def test_fail_closed_authorization_provider():
    provider = FailClosedAuthorizationProvider()

    result = provider(None)

    assert result.allowed is False
    assert result.reason == (
        "AUTHORIZATION_AUTHORITY_NOT_CONFIGURED"
    )


def test_application_container_can_be_built_with_injected_dependencies(
    tmp_path: Path,
):
    settings = Settings(
        claude_model="test-model",
        anthropic_api_key="test-anthropic",
        razorpay_key_id="rzp_test",
        razorpay_key_secret="test-secret",
        mandate_secret_key="x" * 32,
        database_path=str(tmp_path / "state"),
        mandate_ttl_seconds=300,
        max_retries=3,
        request_timeout_seconds=10.0,
    )

    # We only verify construction here. The actual live
    # Claude/Razorpay clients are not called.
    container = ApplicationContainer.from_environment(
        settings=settings,
        authorization_check=DummyAuthorization(),
        policy_provider=lambda _analysis: (
            __import__(
                "models.policy",
                fromlist=["TransactionPolicy"],
            ).TransactionPolicy(
                user_id="user_123",
                agent_id="agent_001",
                max_amount_paise=500000,
                min_amount_paise=10000,
                allowed_merchants=[],
                allowed_categories=[],
                allowed_skus=[],
                max_quantity=10,
                currency="INR",
                bank_rail_available=True,
            )
        ),
    )

    assert container.settings == settings
    assert container.orchestrator is not None
    assert container.transaction_store is not None
    assert container.audit_trail is not None
    assert container.razorpay is not None

    container.razorpay._client = None