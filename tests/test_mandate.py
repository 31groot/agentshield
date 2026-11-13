from datetime import datetime, timedelta, timezone

from engine.mandate import MandateEngine
from models.authorization import AgentAuthorization
from models.intent import IntentItem, IntentProposal
import pytest


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


def make_engine() -> MandateEngine:
    return MandateEngine(
        b"test-mandate-secret"
    )


def test_valid_mandate_verifies():
    engine = make_engine()

    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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
        transaction_id="txn_001",
        authorization=authorization,
        proposal=proposal,
    )

    different_engine = MandateEngine(
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
        transaction_id="txn_001",
        authorization=authorization,
        proposal=proposal_1,
    )

    mandate_2 = engine.create(
        transaction_id="txn_001",
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
        transaction_id="txn_001",
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

def make_persisted_transaction(tmp_path, *, issued_at=None):
    from engine.hashing import IntentHasher
    from engine.transaction_store import SQLiteTransactionStore
    from models.transaction import TransactionRecord

    engine = make_engine()
    authorization = make_authorization()
    proposal = make_proposal()

    mandate = engine.create(
        transaction_id="txn_001",
        authorization=authorization,
        proposal=proposal,
        issued_at=issued_at,
    )

    store = SQLiteTransactionStore(tmp_path / "transactions.db")
    store.create(
        TransactionRecord(
            transaction_id="txn_001",
            intent_id=proposal.intent_id,
            user_id=proposal.user_id,
            agent_id=proposal.agent_id,
            merchant_id=proposal.merchant_id,
            amount_paise=proposal.amount_paise,
            currency=proposal.currency,
            items=proposal.items,
            intent_hash=IntentHasher().hash(authorization, proposal),
            authorization_snapshot=authorization,
            action_type=proposal.action_type,
            mandate=mandate,
            idempotency_key="exec_001",
        )
    )

    return engine, store.get("txn_001")


def test_verify_persisted_accepts_untouched_transaction(tmp_path):
    engine, transaction = make_persisted_transaction(tmp_path)

    assert engine.verify_persisted(transaction=transaction) is True


def test_verify_persisted_rejects_amount_plus_one_paise(tmp_path):
    engine, transaction = make_persisted_transaction(tmp_path)

    tampered = transaction.model_copy(
        update={"amount_paise": transaction.amount_paise + 1}
    )

    assert engine.verify_persisted(transaction=tampered) is False


def test_verify_persisted_rejects_changed_items(tmp_path):
    engine, transaction = make_persisted_transaction(tmp_path)

    tampered = transaction.model_copy(
        update={
            "items": [IntentItem(sku="shoe_001", quantity=2)],
        }
    )

    assert engine.verify_persisted(transaction=tampered) is False


def test_verify_persisted_rejects_raised_authorization_limit(tmp_path):
    engine, transaction = make_persisted_transaction(tmp_path)

    tampered = transaction.model_copy(
        update={
            "authorization_snapshot": (
                transaction.authorization_snapshot.model_copy(
                    update={"max_amount_paise": 99_999_999}
                )
            ),
        }
    )

    assert engine.verify_persisted(transaction=tampered) is False


def test_verify_persisted_rejects_mandate_from_other_transaction(tmp_path):
    engine, transaction = make_persisted_transaction(tmp_path)

    other_mandate = engine.create(
        transaction_id="txn_other",
        authorization=transaction.authorization_snapshot,
        proposal=make_proposal(),
    )

    tampered = transaction.model_copy(
        update={"mandate": other_mandate}
    )

    assert engine.verify_persisted(transaction=tampered) is False


def test_verify_persisted_rejects_altered_signature(tmp_path):
    engine, transaction = make_persisted_transaction(tmp_path)

    signature = transaction.mandate.signature
    altered = ("0" if signature[0] != "0" else "1") + signature[1:]

    tampered = transaction.model_copy(
        update={
            "mandate": transaction.mandate.model_copy(
                update={"signature": altered}
            ),
        }
    )

    assert engine.verify_persisted(transaction=tampered) is False


def test_verify_persisted_expiry_is_enforced_only_when_requested(tmp_path):
    engine, transaction = make_persisted_transaction(
        tmp_path,
        issued_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    assert engine.verify_persisted(transaction=transaction) is False

    assert engine.verify_persisted(
        transaction=transaction,
        enforce_expiry=False,
    ) is True

def test_server_ttl_caps_proposal_ttl():
    engine = MandateEngine(b"x" * 32, max_ttl_seconds=60)
    proposal = make_proposal()          # ttl_seconds defaults to 300

    mandate = engine.create(
        transaction_id="txn_001",
        authorization=make_authorization(),
        proposal=proposal,
    )

    assert (mandate.expires_at - mandate.issued_at).total_seconds() == 60


def test_proposal_ttl_used_when_below_cap():
    engine = MandateEngine(b"x" * 32, max_ttl_seconds=600)
    proposal = make_proposal()

    mandate = engine.create(
        transaction_id="txn_001",
        authorization=make_authorization(),
        proposal=proposal,
    )

    assert (mandate.expires_at - mandate.issued_at).total_seconds() == proposal.ttl_seconds


def test_rejects_non_positive_max_ttl():
    with pytest.raises(ValueError, match="max_ttl_seconds"):
        MandateEngine(b"x" * 32, max_ttl_seconds=0)