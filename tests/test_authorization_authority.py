from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.authorization import (
    AuthorizationEngine,
    SQLiteAuthorizationAuthority,
)
from models.authorization import (
    AgentAuthorization,
    AuthorizationDecision,
    AuthorizationEvaluation,
)
from models.intent import IntentProposal


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


def make_authorization(**overrides) -> AgentAuthorization:
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


@pytest.fixture
def authority(tmp_path: Path) -> SQLiteAuthorizationAuthority:
    db_file = tmp_path / "test_authorizations.db"
    return SQLiteAuthorizationAuthority(str(db_file))


# ---------------------------------------------------------------------------
# Engine Verification Tests (Pure Logic)
# ---------------------------------------------------------------------------


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
    proposal = make_proposal(user_id="attacker_user")
    authorization = make_authorization()

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "USER_MISMATCH"


def test_wrong_agent_is_rejected():
    proposal = make_proposal(agent_id="unknown_agent")
    authorization = make_authorization()

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AGENT_MISMATCH"


def test_inactive_authorization_is_rejected():
    proposal = make_proposal()
    authorization = make_authorization(active=False)

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AUTHORIZATION_INACTIVE"


def test_revoked_authorization_is_rejected():
    proposal = make_proposal()
    authorization = make_authorization(revoked=True)

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AUTHORIZATION_REVOKED"


def test_expired_authorization_is_rejected():
    proposal = make_proposal()
    authorization = make_authorization(
        expires_at=(
            datetime.now(timezone.utc)
            - timedelta(seconds=1)
        )
    )

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is False
    assert result.reason == "AUTHORIZATION_EXPIRED"


def test_no_expiry_is_allowed_when_other_conditions_pass():
    proposal = make_proposal()
    authorization = make_authorization(expires_at=None)

    result = AuthorizationEngine().verify(
        proposal,
        authorization,
    )

    assert result.allowed is True
    assert result.reason == "AUTHORIZATION_APPROVED"


def test_authorization_rejects_amount_above_delegated_limit():
    proposal = make_proposal(amount_paise=600000)
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


# ---------------------------------------------------------------------------
# Authority Check Integration Tests
# ---------------------------------------------------------------------------


def test_authority_check_approves_valid_authorization(
    authority: SQLiteAuthorizationAuthority,
):
    authority.create(
        make_authorization(
            authorization_id="auth_001"
        )
    )

    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is True
    assert evaluation.decision.authorization_id == "auth_001"
    assert evaluation.authorization.authorization_id == "auth_001"


def test_authority_check_missing_authorization(
    authority: SQLiteAuthorizationAuthority,
):
    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is False
    assert evaluation.decision.reason == "AUTHORIZATION_NOT_FOUND"


def test_authority_check_expired_authorization(
    authority: SQLiteAuthorizationAuthority,
):
    authority.create(
        make_authorization(
            authorization_id="expired-auth",
            expires_at=(
                datetime.now(timezone.utc)
                - timedelta(hours=1)
            ),
        )
    )

    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is False
    assert evaluation.decision.reason == "AUTHORIZATION_EXPIRED"
    assert evaluation.authorization.authorization_id == "expired-auth"


def test_authority_check_revoked_authorization(
    authority: SQLiteAuthorizationAuthority,
):
    authority.create(
        make_authorization(
            authorization_id="revoked-auth",
            revoked=True,
        )
    )

    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is False
    assert evaluation.decision.reason == "AUTHORIZATION_REVOKED"
    assert evaluation.authorization.authorization_id == "revoked-auth"


def test_authority_check_inactive_authorization(
    authority: SQLiteAuthorizationAuthority,
):
    authority.create(
        make_authorization(
            authorization_id="inactive-auth",
            active=False,
        )
    )

    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is False
    assert evaluation.decision.reason == "AUTHORIZATION_INACTIVE"
    assert evaluation.authorization.authorization_id == "inactive-auth"


def test_authority_check_selects_active_over_expired(
    authority: SQLiteAuthorizationAuthority,
):
    authority.create(
        make_authorization(
            authorization_id="expired-auth",
            expires_at=(
                datetime.now(timezone.utc)
                - timedelta(hours=1)
            ),
        )
    )

    authority.create(
        make_authorization(
            authorization_id="active-auth",
            expires_at=(
                datetime.now(timezone.utc)
                + timedelta(hours=1)
            ),
        )
    )

    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is True
    assert evaluation.decision.authorization_id == "active-auth"
    assert evaluation.authorization.authorization_id == "active-auth"


def test_authority_check_selects_valid_within_bounds(
    authority: SQLiteAuthorizationAuthority,
):
    authority.create(
        make_authorization(
            authorization_id="low-limit-auth",
            max_amount_paise=100000,
        )
    )

    authority.create(
        make_authorization(
            authorization_id="valid-auth",
            max_amount_paise=500000,
        )
    )

    evaluation = authority.check(
        make_proposal(),
    )

    assert evaluation.decision.allowed is True
    assert evaluation.decision.authorization_id == "valid-auth"
    assert evaluation.authorization.authorization_id == "valid-auth"