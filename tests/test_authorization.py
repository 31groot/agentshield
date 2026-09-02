from datetime import datetime, timedelta, timezone

import pytest

from engine.authorization import AuthorizationEngine
from models.intent import IntentProposal
from models.authorization import AgentAuthorization
from models.authorization import (
    AuthorizationDecision,
    AuthorizationEvaluation,
)


def make_proposal(**overrides) -> IntentProposal:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "intent_id": "intent_001",
        "raw_user_prompt": "Buy running shoes under ₹5000.",
        "merchant_id": "merchant_001",
        "amount_paise": 450000,
        "currency": "INR",
        "items": [
            {
                "sku": "shoe_001",
                "quantity": 1,
            }
        ],
        "action_type": "CREATE_ORDER",
        "nonce": "nonce_001",
        "ttl_seconds": 300,
    }

    payload.update(overrides)

    return IntentProposal.model_validate(payload)


def make_authorization(
    **overrides,
) -> AgentAuthorization:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "authorization_id": "auth_001",
        "active": True,
        "revoked": False,
        "max_amount_paise": 500000,
        "allowed_merchants": ["merchant_001"],
        "allowed_categories": ["footwear"],
        "allowed_skus": ["shoe_001"],
        "max_quantity": 2,
        "currency": "INR",
        "expires_at": (
            datetime.now(timezone.utc)
            + timedelta(hours=1)
        ),
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


def test_authorization_rejects_amount_above_delegated_limit():
    proposal = make_proposal(
        amount_paise=600000
    )

    authorization = make_authorization(
        max_amount_paise=500000
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AMOUNT_EXCEEDS_AUTHORIZATION_LIMIT"

def test_authorization_rejects_unauthorized_merchant():
    proposal = make_proposal(
        merchant_id="merchant_999"
    )

    authorization = make_authorization(
        allowed_merchants=["merchant_001"]
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "MERCHANT_NOT_AUTHORIZED"


def test_authorization_rejects_unauthorized_sku():
    proposal = make_proposal(
        items=[
            {
                "sku": "shoe_999",
                "quantity": 1,
            }
        ]
    )

    authorization = make_authorization(
        allowed_skus=["shoe_001"]
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "SKU_NOT_AUTHORIZED"


def test_authorization_rejects_quantity_above_delegated_limit():
    proposal = make_proposal(
        items=[
            {
                "sku": "shoe_001",
                "quantity": 3,
            }
        ]
    )

    authorization = make_authorization(
        max_quantity=2
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "QUANTITY_EXCEEDS_AUTHORIZATION_LIMIT"

def test_authorization_evaluation_binds_decision_to_record():
    authorization = make_authorization()

    evaluation = AuthorizationEvaluation(
        decision=AuthorizationDecision(
            allowed=True,
            reason="AUTHORIZATION_APPROVED",
            authorization_id=authorization.authorization_id,
        ),
        authorization=authorization,
    )

    assert evaluation.decision.authorization_id == (
        evaluation.authorization.authorization_id
    )

def test_authorization_evaluation_rejects_mismatched_record():
    authorization = make_authorization(
        authorization_id="auth-actual",
    )

    with pytest.raises(ValueError):
        AuthorizationEvaluation(
            decision=AuthorizationDecision(
                allowed=True,
                reason="AUTHORIZATION_APPROVED",
                authorization_id="auth-other",
            ),
            authorization=authorization,
        )
def test_authorization_evaluation_allows_missing_record_for_unidentified_denial():
    evaluation = AuthorizationEvaluation(
        decision=AuthorizationDecision(
            allowed=False,
            reason="AUTHORIZATION_NOT_FOUND",
            authorization_id=None,
        ),
        authorization=None,
    )

    assert evaluation.decision.allowed is False
    assert evaluation.authorization is None


def test_authorization_evaluation_rejects_allowed_without_record():
    with pytest.raises(ValueError):
        AuthorizationEvaluation(
            decision=AuthorizationDecision(
                allowed=True,
                reason="AUTHORIZATION_APPROVED",
                authorization_id="auth-001",
            ),
            authorization=None,
        )