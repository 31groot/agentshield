from datetime import datetime, timedelta, timezone

from engine.authorization import AuthorizationEngine
from models.intent import IntentProposal
from models.policy import AgentAuthorization


def make_proposal(**overrides) -> IntentProposal:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "intent_id": "intent_001",
        "raw_user_prompt": "Buy running shoes under ₹5000.",
        "merchant_id": "merchant_001",
        "requested_amount_inr": 4500.0,
        "currency": "INR",
        "sku_list": ["shoe_001"],
        "quantity": 1,
        "action_type": "CREATE_ORDER",
        "nonce": "nonce_001",
        "ttl_seconds": 300,
    }

    payload.update(overrides)

    return IntentProposal.model_validate(payload)


def make_authorization(**overrides) -> AgentAuthorization:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "authorization_id": "auth_001",
        "active": True,
        "revoked": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }

    payload.update(overrides)

    return AgentAuthorization.model_validate(payload)


def test_authorized_agent_is_approved():
    proposal = make_proposal()
    authorization = make_authorization()

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is True
    assert result.reason == "AUTHORIZATION_APPROVED"
    assert result.authorization_id == "auth_001"


def test_wrong_user_is_rejected():
    proposal = make_proposal(
        user_id="attacker_user"
    )

    authorization = make_authorization()

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "USER_MISMATCH"


def test_wrong_agent_is_rejected():
    proposal = make_proposal(
        agent_id="unknown_agent"
    )

    authorization = make_authorization()

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AGENT_MISMATCH"


def test_inactive_authorization_is_rejected():
    proposal = make_proposal()

    authorization = make_authorization(
        active=False
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AUTHORIZATION_INACTIVE"


def test_revoked_authorization_is_rejected():
    proposal = make_proposal()

    authorization = make_authorization(
        revoked=True
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AUTHORIZATION_REVOKED"


def test_expired_authorization_is_rejected():
    proposal = make_proposal()

    authorization = make_authorization(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AUTHORIZATION_EXPIRED"


def test_no_expiry_is_allowed_when_other_conditions_pass():
    proposal = make_proposal()

    authorization = make_authorization(
        expires_at=None
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is True
    assert result.reason == "AUTHORIZATION_APPROVED"


def test_authorization_engine_does_not_evaluate_transaction_amount():
    
    proposal = make_proposal(
        requested_amount_inr=100000.0
    )

    authorization = make_authorization()

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is True