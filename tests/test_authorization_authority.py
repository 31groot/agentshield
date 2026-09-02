from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.authorization import (
    AuthorizationError,
    AuthorizationEngine,
    SQLiteAuthorizationAuthority,
)
from models.authorization import AgentAuthorization
from models.intent import IntentItem, IntentProposal


def make_proposal(
    *,
    user_id: str = "user_123",
    agent_id: str = "agent_001",
) -> IntentProposal:
    return IntentProposal(
        user_id=user_id,
        agent_id=agent_id,
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


def make_authorization(
    *,
    authorization_id: str = "auth_001",
    user_id: str = "user_123",
    agent_id: str = "agent_001",
    active: bool = True,
    revoked: bool = False,
    max_amount_paise: int = 500000,
    allowed_merchants: list[str] | None = None,
    allowed_categories: list[str] | None = None,
    allowed_skus: list[str] | None = None,
    max_quantity: int = 2,
    currency: str = "INR",
    expires_at: datetime | None = None,
) -> AgentAuthorization:
    return AgentAuthorization(
        user_id=user_id,
        agent_id=agent_id,
        authorization_id=authorization_id,
        active=active,
        revoked=revoked,
        max_amount_paise=max_amount_paise,
        allowed_merchants=(
            ["merchant_001"]
            if allowed_merchants is None
            else allowed_merchants
        ),
        allowed_categories=(
            ["footwear"]
            if allowed_categories is None
            else allowed_categories
        ),
        allowed_skus=(
            ["shoe_001"]
            if allowed_skus is None
            else allowed_skus
        ),
        max_quantity=max_quantity,
        currency=currency,
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )

def test_authorization_engine_approves_valid_authorization():
    engine = AuthorizationEngine()

    decision = engine.verify(
        make_proposal(),
        make_authorization(),
    )

    assert decision.allowed is True
    assert decision.reason == "AUTHORIZATION_APPROVED"
    assert decision.authorization_id == "auth_001"


def test_authorization_engine_rejects_expired_authorization():
    engine = AuthorizationEngine()

    authorization = make_authorization(
        expires_at=(
            datetime.now(timezone.utc)
            - timedelta(seconds=1)
        ),
    )

    decision = engine.verify(
        make_proposal(),
        authorization,
    )

    assert decision.allowed is False
    assert decision.reason == "AUTHORIZATION_EXPIRED"


def test_authorization_engine_rejects_revoked_authorization():
    engine = AuthorizationEngine()

    decision = engine.verify(
        make_proposal(),
        make_authorization(revoked=True, active=False),
    )

    assert decision.allowed is False
    assert decision.reason == "AUTHORIZATION_REVOKED"


def test_authorization_engine_rejects_user_mismatch():
    engine = AuthorizationEngine()

    decision = engine.verify(
        make_proposal(user_id="attacker"),
        make_authorization(),
    )

    assert decision.allowed is False
    assert decision.reason == "USER_MISMATCH"


def test_authorization_engine_rejects_agent_mismatch():
    engine = AuthorizationEngine()

    decision = engine.verify(
        make_proposal(agent_id="agent_attacker"),
        make_authorization(),
    )

    assert decision.allowed is False
    assert decision.reason == "AGENT_MISMATCH"


def test_create_and_reload_authorization(tmp_path: Path):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authorization = make_authorization()

    authority.create(authorization)

    reloaded = authority.get("auth_001")

    assert reloaded == authorization


def test_duplicate_authorization_id_is_rejected(tmp_path: Path):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(make_authorization())

    with pytest.raises(
        AuthorizationError,
        match="already exists",
    ):
        authority.create(make_authorization())


def test_find_for_agent_returns_matching_records(tmp_path: Path):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(
        make_authorization(
            authorization_id="auth_001",
        )
    )

    authority.create(
        make_authorization(
            authorization_id="auth_002",
        )
    )

    authority.create(
        make_authorization(
            authorization_id="auth_003",
            agent_id="other-agent",
        )
    )

    records = authority.find_for_agent(
        user_id="user_123",
        agent_id="agent_001",
    )

    assert len(records) == 2
    assert {
        record.authorization_id
        for record in records
    } == {"auth_001", "auth_002"}


def test_check_approves_from_server_owned_record(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(
        make_authorization(
            authorization_id="auth_001",
        )
    )

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is True
    assert decision.authorization_id == "auth_001"


def test_check_rejects_missing_authorization(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is False
    assert decision.reason == "AUTHORIZATION_NOT_FOUND"


def test_check_rejects_only_expired_authorization(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(
        make_authorization(
            expires_at=(
                datetime.now(timezone.utc)
                - timedelta(seconds=1)
            ),
        )
    )

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is False
    assert decision.reason == "AUTHORIZATION_EXPIRED"


def test_revoke_persists_revocation(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(make_authorization())

    revoked = authority.revoke("auth_001")

    assert revoked.revoked is True
    assert revoked.active is False

    reloaded = authority.get("auth_001")

    assert reloaded is not None
    assert reloaded.revoked is True
    assert reloaded.active is False

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is False
    assert decision.reason == "AUTHORIZATION_REVOKED"


def test_deactivate_persists_inactive_state(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(make_authorization())

    deactivated = authority.deactivate("auth_001")

    assert deactivated.active is False
    assert deactivated.revoked is False

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is False
    assert decision.reason == "AUTHORIZATION_INACTIVE"


def test_multiple_records_allow_active_authorization_when_older_one_is_expired(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(
        make_authorization(
            authorization_id="expired-auth",
            expires_at=(
                datetime.now(timezone.utc)
                - timedelta(seconds=1)
            ),
        )
    )

    authority.create(
        make_authorization(
            authorization_id="active-auth",
        )
    )

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is True
    assert decision.authorization_id == "active-auth"

def test_multiple_records_skip_authorization_that_cannot_cover_proposal(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    authority.create(
        make_authorization(
            authorization_id="narrow-auth",
            max_amount_paise=100000,
        )
    )

    authority.create(
        make_authorization(
            authorization_id="valid-auth",
            max_amount_paise=500000,
        )
    )

    decision = authority.check(
        make_proposal(),
    )

    assert decision.allowed is True
    assert decision.authorization_id == "valid-auth"

def test_duplicate_authorization_cannot_replace_existing_bounds(
    tmp_path: Path,
):
    authority = SQLiteAuthorizationAuthority(
        str(tmp_path / "authorization.db")
    )

    original = make_authorization(
        authorization_id="auth_001",
        max_amount_paise=500000,
        allowed_merchants=["merchant_001"],
        allowed_skus=["shoe_001"],
        max_quantity=2,
    )

    authority.create(original)

    replacement = make_authorization(
        authorization_id="auth_001",
        max_amount_paise=5000000,
        allowed_merchants=["merchant_999"],
        allowed_skus=["dangerous_001"],
        max_quantity=100,
    )

    with pytest.raises(
        AuthorizationError,
        match="already exists",
    ):
        authority.create(replacement)

    stored = authority.get("auth_001")

    assert stored == original