from datetime import datetime, timedelta, timezone

from engine.mandate import AP2AlignedMandateEngine
from models.authorization import AgentAuthorization
from models.intent import IntentItem, IntentProposal


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
        "created_at": datetime.now(timezone.utc),
        "expires_at": None,
    }

    payload.update(overrides)

    return AgentAuthorization.model_validate(payload)

def make_proposal(**overrides):
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
        "created_at": datetime.now(timezone.utc),
        "ttl_seconds": 300,
    }

    payload.update(overrides)

    return IntentProposal.model_validate(payload)


def make_engine() -> AP2AlignedMandateEngine:
    return AP2AlignedMandateEngine(
        b"test-mandate-secret"
    )


def test_valid_mandate_verifies():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=proposal,
    ) is True


def test_amount_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_proposal = proposal.model_copy(
        update={
            "amount_paise": 490000,
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=mutated_proposal,
    ) is False


def test_merchant_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_proposal = proposal.model_copy(
        update={
            "merchant_id": "merchant_999",
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=mutated_proposal,
    ) is False


def test_sku_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_proposal = proposal.model_copy(
        update={
            "items": [
                IntentItem(
                    sku="detergent_001",
                    quantity=1,
                )
            ]
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=mutated_proposal,
    ) is False

def test_quantity_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_proposal = proposal.model_copy(
        update={
            "items": [
                IntentItem(
                    sku="shoe_001",
                    quantity=2,
                )
            ]
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=mutated_proposal,
    ) is False

def test_authorization_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_authorization = authorization.model_copy(
        update={
            "max_amount_paise": 600000,
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=mutated_authorization,
        proposal=proposal,
    ) is False


def test_nonce_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_proposal = proposal.model_copy(
        update={
            "nonce": "different_nonce",
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=mutated_proposal,
    ) is False


def test_expired_mandate_is_rejected():
    engine = make_engine()

    authorization = make_authorization()

    issued_at = datetime(
        2026,
        1,
        1,
        12,
        0,
        0,
        tzinfo=timezone.utc,
    )

    proposal = make_proposal(
        created_at=issued_at,
        ttl_seconds=300,
    )

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
        issued_at=issued_at,
    )

    now = issued_at + timedelta(seconds=301)

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=proposal,
        now=now,
    ) is False


def test_mandate_cannot_be_used_before_issued_at():
    engine = make_engine()

    authorization = make_authorization()

    issued_at = datetime.now(timezone.utc)

    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
        issued_at=issued_at,
    )

    now = issued_at - timedelta(seconds=1)

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=proposal,
        now=now,
    ) is False


def test_signature_tampering_is_detected():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    tampered = mandate.model_copy(
        update={
            "signature": "tampered-signature",
        }
    )

    assert engine.verify(
        mandate=tampered,
        authorization=authorization,
        proposal=proposal,
    ) is False


def test_wrong_secret_cannot_verify_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    different_engine = AP2AlignedMandateEngine(
        b"different-secret"
    )

    assert different_engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=proposal,
    ) is False


def test_different_nonces_produce_different_signatures():
    engine = make_engine()

    authorization = make_authorization()

    proposal_1 = make_proposal(
        nonce="nonce_001"
    )

    proposal_2 = make_proposal(
        nonce="nonce_002"
    )

    mandate_1 = engine.create(
        authorization=authorization,
        proposal=proposal_1,
    )

    mandate_2 = engine.create(
        authorization=authorization,
        proposal=proposal_2,
    )

    assert mandate_1.intent_hash == mandate_2.intent_hash
    assert mandate_1.signature != mandate_2.signature


def test_action_type_mutation_invalidates_mandate():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal(
        action_type="CREATE_ORDER"
    )

    mandate = engine.create(
        authorization=authorization,
        proposal=proposal,
    )

    mutated_proposal = proposal.model_copy(
        update={
            "action_type": "REFUND_AND_REROUTE"
        }
    )

    assert engine.verify(
        mandate=mandate,
        authorization=authorization,
        proposal=mutated_proposal,
    ) is False