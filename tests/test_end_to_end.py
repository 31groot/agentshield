from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from application.orchestrator import AgentShieldOrchestrator, OrchestrationError
from engine.audit import SQLiteAuditTrail
from engine.hashing import IntentHasher
from engine.idempotency import WALIdempotencyStore
from engine.mandate import AP2AlignedMandateEngine
from engine.policy import DeterministicPolicyEngine
from engine.reconciliation import ReconciliationEngine, WebhookEventStore
from engine.transaction_store import SQLiteTransactionStore
from models.audit import AuditEventType
from models.intent import (
    AgentRequestAnalysis,
    AuthorizationInterpretation,
    IntentItem,
    IntentProposal,
)
from models.transaction import TransactionState
from models.authorization import AuthorizationDecision
from models.policy import TransactionPolicy
from models.webhook import WebhookEvent, WebhookEventType


def make_analysis() -> AgentRequestAnalysis:
    now = datetime.now(timezone.utc)

    authorization = AuthorizationInterpretation(
        max_amount_paise=500000,
        currency="INR",
        product_constraints=["running shoes"],
        allowed_merchants=[],
        max_quantity=1,
        constraints=[
            "running shoes",
            "maximum ₹5000",
        ],
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
        created_at=now,
        ttl_seconds=300,
    )

    return AgentRequestAnalysis(
        raw_user_prompt="Buy running shoes under ₹5000.",
        authorization=authorization,
        intent_proposal=proposal,
    )


class FakeClaude:
    def parse(
        self,
        user_message,
        *,
        user_id,
        agent_id,
        intent_id,
        merchant_context=None,
    ):
        return make_analysis()


class FakeRazorpayOrder:
    order_id = "order_001"
    amount_paise = 450000
    currency = "INR"
    status = "created"


class FakeRazorpay:
    async def create_order(
        self,
        *,
        amount_paise,
        currency,
        receipt,
        notes,
    ):
        assert amount_paise == 450000
        assert currency == "INR"
        assert receipt == "txn_001"
        return FakeRazorpayOrder()


def approved_authorization() -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=True,
        reason="AUTHORIZATION_APPROVED",
        authorization_id="auth_001",
    )


def make_policy_provider():
    def provider(_analysis):
        return TransactionPolicy(
            user_id="user_123",
            agent_id="agent_001",
            max_amount_paise=500000,
            min_amount_paise=10000,
            allowed_merchants=["merchant_001"],
            allowed_categories=[],
            allowed_skus=["shoe_001"],
            max_quantity=2,
            currency="INR",
            bank_rail_available=True,
        )

    return provider


@pytest.mark.asyncio
async def test_full_governed_flow_persists_and_reconciles(
    tmp_path: Path,
):
    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )
    transaction_store = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )

    orchestrator = AgentShieldOrchestrator(
        claude=FakeClaude(),
        authorization_check=lambda analysis: (
            approved_authorization()
        ),
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=AP2AlignedMandateEngine(
            b"test-secret-key"
        ),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=FakeRazorpay(),
        policy_provider=make_policy_provider(),
        audit_trail=audit_trail,
        transaction_store=transaction_store,
    )

    result = await orchestrator.execute(
        user_message="Buy running shoes under ₹5000.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        transaction_id="txn_001",
        idempotency_key="exec_001",
    )

    assert result.transaction.state == TransactionState.DISPATCHED
    assert result.transaction.razorpay_order_id == "order_001"

    persisted = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    ).get("txn_001")
    assert persisted is not None
    assert persisted.state == TransactionState.DISPATCHED
    assert persisted.razorpay_order_id == "order_001"

    webhook_store = WebhookEventStore(
        tmp_path / "webhook.db"
    )
    reconciliation = ReconciliationEngine(
        webhook_store=webhook_store,
        transaction_store=transaction_store,
        audit_trail=audit_trail,
    )

    webhook = WebhookEvent.model_validate(
        {
            "event_id": "evt_001",
            "event_type": WebhookEventType.PAYMENT_CAPTURED,
            "payment_id": "pay_001",
            "order_id": "order_001",
            "amount_paise": 450000,
            "currency": "INR",
        }
    )

    reconciled = reconciliation.reconcile_event(
        event=webhook,
    )

    assert reconciled.state == TransactionState.SUCCESS
    assert reconciled.razorpay_payment_id == "pay_001"

    final_store = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )
    final_transaction = final_store.get("txn_001")

    assert final_transaction is not None
    assert final_transaction.state == TransactionState.SUCCESS
    assert final_transaction.razorpay_order_id == "order_001"
    assert final_transaction.razorpay_payment_id == "pay_001"

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )
    assert events[-2].event_type == AuditEventType.WEBHOOK_RECEIVED
    assert events[-1].event_type == AuditEventType.PAYMENT_RECONCILED
    assert audit_trail.verify_chain() is True


def test_unknown_state_is_not_treated_as_retryable(
    tmp_path: Path,
):
    now = datetime.now(timezone.utc)
    transaction_store = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )

    from models.intent import IntentItem
    from models.transaction import TransactionRecord

    transaction = TransactionRecord.model_validate(
        {
            "transaction_id": "txn_unknown",
            "intent_id": "intent_unknown",
            "user_id": "user_123",
            "agent_id": "agent_001",
            "merchant_id": "merchant_001",
            "amount_paise": 450000,
            "currency": "INR",
            "items": [
                IntentItem(
                    sku="shoe_001",
                    quantity=1,
                )
            ],
            "intent_hash": "a" * 64,
            "idempotency_key": "exec_unknown",
            "razorpay_order_id": "order_unknown",
            "razorpay_payment_id": None,
            "state": TransactionState.UNKNOWN,
            "created_at": now,
            "updated_at": now,
        }
    )

    transaction_store.create(transaction)
    stored = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    ).get("txn_unknown")

    assert stored is not None
    assert stored.state == TransactionState.UNKNOWN
    assert stored.state != TransactionState.FAILED_SAFE_TO_RETRY
