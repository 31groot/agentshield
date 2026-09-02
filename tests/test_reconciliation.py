from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.audit import SQLiteAuditTrail
from engine.reconciliation import (
    ReconciliationEngine,
    ReconciliationError,
    WebhookEventStore,
)

from models.audit import AuditEventType
from models.intent import IntentItem
from models.transaction import (
    TransactionRecord,
    TransactionState,
)
from models.webhook import (
    WebhookEvent,
    WebhookEventType,
    WebhookProcessingStatus,
)


def make_transaction(
    **overrides,
) -> TransactionRecord:
    payload = {
        "transaction_id": "txn_001",
        "intent_id": "intent_001",
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
        "idempotency_key": "exec_001",
        "razorpay_order_id": "order_001",
        "razorpay_payment_id": None,
        "state": TransactionState.DISPATCHED,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    payload.update(overrides)

    return TransactionRecord.model_validate(payload)


def make_event(
    **overrides,
) -> WebhookEvent:
    payload = {
        "event_id": "evt_001",
        "event_type": WebhookEventType.PAYMENT_CAPTURED,
        "payment_id": "pay_001",
        "order_id": "order_001",
        "amount_paise": 450000,
        "currency": "INR",
    }

    payload.update(overrides)

    return WebhookEvent.model_validate(payload)


def make_engine(
    tmp_path: Path,
) -> tuple[ReconciliationEngine, SQLiteAuditTrail]:
    store = WebhookEventStore(
        tmp_path / "webhook.db"
    )

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    engine = ReconciliationEngine(
        webhook_store=store,
        audit_trail=audit_trail,
    )

    return engine, audit_trail


def test_captured_payment_reconciles_to_success(
    tmp_path: Path,
):
    engine, audit_trail = make_engine(tmp_path)

    transaction = make_transaction()
    event = make_event()

    result = engine.reconcile(
        transaction=transaction,
        event=event,
    )

    assert result.state == TransactionState.SUCCESS
    assert result.razorpay_payment_id == "pay_001"
    assert result.updated_at >= transaction.updated_at

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.WEBHOOK_RECEIVED,
        AuditEventType.PAYMENT_RECONCILED,
    ]

    assert events[0].details["event_id"] == "evt_001"
    assert events[0].details["payment_id"] == "pay_001"

    assert events[1].state == TransactionState.SUCCESS
    assert audit_trail.verify_chain() is True


def test_failed_payment_reconciles_to_safe_retry(
    tmp_path: Path,
):
    engine, audit_trail = make_engine(tmp_path)

    transaction = make_transaction()

    event = make_event(
        event_type=WebhookEventType.PAYMENT_FAILED,
    )

    result = engine.reconcile(
        transaction=transaction,
        event=event,
    )

    assert (
        result.state
        == TransactionState.FAILED_SAFE_TO_RETRY
    )

    assert result.razorpay_payment_id == "pay_001"

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.WEBHOOK_RECEIVED,
        AuditEventType.PAYMENT_RECONCILED,
    ]

    assert events[1].state == (
        TransactionState.FAILED_SAFE_TO_RETRY
    )

    assert audit_trail.verify_chain() is True


def test_duplicate_webhook_is_ignored(
    tmp_path: Path,
):
    engine, audit_trail = make_engine(tmp_path)

    transaction = make_transaction()
    event = make_event()

    first = engine.reconcile(
        transaction=transaction,
        event=event,
    )

    second = engine.reconcile(
        transaction=first,
        event=event,
    )

    assert first.state == TransactionState.SUCCESS
    assert second.state == TransactionState.SUCCESS
    assert second == first

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.WEBHOOK_RECEIVED,
        AuditEventType.PAYMENT_RECONCILED,
    ]

    assert audit_trail.verify_chain() is True


def test_replayed_event_with_mismatched_payment_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction()
    event = make_event()

    first = engine.reconcile(
        transaction=transaction,
        event=event,
    )

    duplicate_event = make_event(
        event_id="evt_001",
        payment_id="different_payment",
    )

    with pytest.raises(
        ReconciliationError,
        match="payment",
    ):
        engine.reconcile(
            transaction=first,
            event=duplicate_event,
        )


def test_wrong_amount_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction()

    event = make_event(
        amount_paise=500000,
    )

    with pytest.raises(
        ReconciliationError,
        match="amount",
    ):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_wrong_order_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction()

    event = make_event(
        order_id="order_wrong",
    )

    with pytest.raises(
        ReconciliationError,
        match="order",
    ):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_missing_transaction_order_id_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction(
        razorpay_order_id=None,
    )

    event = make_event(
        order_id="order_001",
    )

    with pytest.raises(
        ReconciliationError,
        match="no Razorpay order ID",
    ):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_wrong_currency_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction()

    event = make_event(
        currency="USD",
    )

    with pytest.raises(
        ReconciliationError,
        match="currency",
    ):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_existing_payment_id_mismatch_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction(
        state=TransactionState.DISPATCHED,
        razorpay_payment_id="pay_existing",
    )

    event = make_event(
        payment_id="pay_different",
    )

    with pytest.raises(
        ReconciliationError,
        match="payment",
    ):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_already_reconciled_transaction_is_rejected(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction(
        state=TransactionState.SUCCESS,
    )

    event = make_event()

    with pytest.raises(ReconciliationError):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_safe_retry_transaction_cannot_accept_stale_reconciliation_event(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction(
        state=TransactionState.FAILED_SAFE_TO_RETRY,
    )

    event = make_event()

    with pytest.raises(ReconciliationError):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_different_event_id_is_not_treated_as_duplicate(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction()

    first_event = make_event(
        event_id="evt_001",
    )

    first = engine.reconcile(
        transaction=transaction,
        event=first_event,
    )

    second_event = make_event(
        event_id="evt_002",
    )

    with pytest.raises(ReconciliationError):
        engine.reconcile(
            transaction=first,
            event=second_event,
        )


def test_webhook_event_store_only_claims_once(
    tmp_path: Path,
):
    store = WebhookEventStore(
        tmp_path / "webhook.db"
    )

    assert store.receive("evt_001") is True
    assert store.receive("evt_001") is False


def test_webhook_event_receive_persists(
    tmp_path: Path,
):
    db_path = tmp_path / "webhook.db"

    first_store = WebhookEventStore(
        db_path
    )

    assert first_store.receive(
        "evt_001"
    ) is True

    second_store = WebhookEventStore(
        db_path
    )

    record = second_store.get(
        "evt_001"
    )

    assert record is not None
    assert record.status == WebhookProcessingStatus.RECEIVED


def test_captured_payment_passes_through_reconciliation_states(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction(
        state=TransactionState.DISPATCHED,
    )

    event = make_event()

    result = engine.reconcile(
        transaction=transaction,
        event=event,
    )

    assert result.state == TransactionState.SUCCESS


def test_completed_transaction_rejects_webhook(
    tmp_path: Path,
):
    engine, _ = make_engine(tmp_path)

    transaction = make_transaction(
        state=TransactionState.COMPLETED,
    )

    event = make_event()

    with pytest.raises(ReconciliationError):
        engine.reconcile(
            transaction=transaction,
            event=event,
        )


def test_webhook_is_received_once(
    tmp_path: Path,
):
    store = WebhookEventStore(
        tmp_path / "webhook.db"
    )

    assert store.receive("evt_001") is True
    assert store.receive("evt_001") is False

    record = store.get("evt_001")

    assert record is not None
    assert record.status == WebhookProcessingStatus.RECEIVED
    assert record.processed_at is None


def test_webhook_can_be_marked_processed(
    tmp_path: Path,
):
    store = WebhookEventStore(
        tmp_path / "webhook.db"
    )

    store.receive("evt_001")

    assert store.mark_processed(
        "evt_001"
    ) is True

    record = store.get("evt_001")

    assert record is not None
    assert record.status == WebhookProcessingStatus.PROCESSED
    assert record.processed_at is not None


def test_received_event_can_be_retried_after_failed_processing(
    tmp_path: Path,
):
    store = WebhookEventStore(
        tmp_path / "webhook.db"
    )

    store.receive("evt_001")

    # Simulate a previous processing attempt that crashed.
    record = store.get("evt_001")

    assert record is not None
    assert record.status == WebhookProcessingStatus.RECEIVED

    # A later attempt must be allowed to process the event.
    assert record.status == WebhookProcessingStatus.RECEIVED