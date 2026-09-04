from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from application.container import (
    ApplicationContainer,
    FailClosedAuthorizationProvider,
)
from config import Settings
from models.authorization import (
    AgentAuthorization,
    AuthorizationDecision,
    AuthorizationEvaluation,
)
from models.intent import IntentItem, IntentProposal
from models.policy import TransactionPolicy


class DummyAuthorization:
    def __call__(self, analysis):
        authorization = AgentAuthorization(
            user_id="user_123",
            agent_id="agent_001",
            authorization_id="test-auth",
            active=True,
            revoked=False,
            max_amount_paise=500000,
            allowed_merchants=["merchant_001"],
            allowed_categories=["footwear"],
            allowed_skus=["shoe_001"],
            max_quantity=2,
            currency="INR",
        )

        return AuthorizationEvaluation(
            decision=AuthorizationDecision(
                allowed=True,
                reason="TEST_APPROVED",
                authorization_id=authorization.authorization_id,
            ),
            authorization=authorization,
        )


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        claude_model="test-model",
        anthropic_api_key="test-anthropic",
        razorpay_key_id="rzp_test",
        razorpay_key_secret="test-secret",
        mandate_secret_key="x" * 32,
        webhook_secret="test-webhook-secret",
        api_token="12345678901234567890123456789012",
        api_user_id="user_123",
        api_agent_id="agent_001",
        database_path=str(tmp_path / "state"),
        mandate_ttl_seconds=300,
        max_retries=3,
        request_timeout_seconds=10.0,
    )

def make_policy(_analysis) -> TransactionPolicy:
    return TransactionPolicy(
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


def test_fail_closed_authorization_provider():
    provider = FailClosedAuthorizationProvider()

    result = provider(None)

    assert result.decision.allowed is False
    assert result.decision.reason == (
        "AUTHORIZATION_AUTHORITY_NOT_CONFIGURED"
    )


def test_application_container_can_be_built_with_injected_dependencies(
    tmp_path: Path,
):
    settings = make_settings(tmp_path)

    container = ApplicationContainer.from_environment(
        settings=settings,
        authorization_check=DummyAuthorization(),
        policy_provider=make_policy,
    )

    assert container.settings == settings
    assert container.orchestrator is not None
    assert container.transaction_store is not None
    assert container.audit_trail is not None
    assert container.authorization_authority is not None
    assert container.razorpay is not None

    container.razorpay._client = None


def test_application_container_uses_server_owned_authorization_authority(
    tmp_path: Path,
):
    settings = make_settings(tmp_path)

    container = ApplicationContainer.from_environment(
        settings=settings,
        policy_provider=make_policy,
    )

    authorization = container.authorization_authority

    assert authorization is not None

    assert authorization.get("missing") is None

    assert (
        container.orchestrator._authorization_check
        is not None
    )


def test_server_owned_authorization_can_be_persisted_through_container(
    tmp_path: Path,
):
    settings = make_settings(tmp_path)

    container = ApplicationContainer.from_environment(
        settings=settings,
        policy_provider=make_policy,
    )

    authorization = AgentAuthorization(
        user_id="user_123",
        agent_id="agent_001",
        authorization_id="auth_001",
        active=True,
        revoked=False,
        max_amount_paise=500000,
        allowed_merchants=["merchant_001"],
        allowed_categories=["footwear"],
        allowed_skus=["shoe_001"],
        max_quantity=2,
        currency="INR",
    )

    container.authorization_authority.create(
        authorization
    )

    proposal = IntentProposal(
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        raw_user_prompt="Buy running shoes under ₹5000.",
        merchant_id="merchant_001",
        amount_paise=450000,
        currency="INR",
        items=[
            IntentItem(
                sku="shoe_001",
                quantity=1,
            )
        ],
        action_type="CREATE_ORDER",
        nonce="nonce_001",
        created_at=datetime.now(timezone.utc),
        ttl_seconds=300,
    )

    evaluation = container.authorization_authority.check(
        proposal
    )

    assert evaluation.decision.allowed is True
    assert evaluation.decision.authorization_id == "auth_001"
    assert evaluation.authorization.authorization_id == "auth_001"
