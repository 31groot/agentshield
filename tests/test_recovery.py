from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.audit import SQLiteAuditTrail
from models.audit import AuditEventType
from models.intent import IntentItem
from models.transaction import (
    TransactionRecord,
    TransactionState,
)
from recovery.transaction import (
    RecoveryError,
    TransactionRecoveryEngine,
)


def make_transaction(
    *,
    state: TransactionState,
    **overrides,
) -> TransactionRecord:
    now = datetime.now(timezone.utc)

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
        "razorpay_payment_id": "pay_001",
        "state": state,
        "created_at": now,
        "updated_at": now,
    }

    payload.update(overrides)

    return TransactionRecord.model_validate(payload)


@pytest.fixture
def recovery_context(
    tmp_path: Path,
) -> tuple[TransactionRecoveryEngine, SQLiteAuditTrail]:
    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    engine = TransactionRecoveryEngine(
        audit_trail=audit_trail,
    )

    return engine, audit_trail


# Safe retry


def test_failed_safe_to_retry_can_prepare_retry(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.FAILED_SAFE_TO_RETRY,
    )

    original_updated_at = transaction.updated_at

    result = engine.prepare_retry(transaction)

    assert result.action == "RETRY_EXECUTION"
    assert (
        result.transaction.state
        == TransactionState.LOCK_ACQUIRED
    )
    assert result.transaction.updated_at >= original_updated_at

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.RECOVERY_STARTED,
    ]

    assert events[0].state == TransactionState.LOCK_ACQUIRED

    assert events[0].details == {
        "action": "RETRY_EXECUTION",
    }

    assert audit_trail.verify_chain() is True


def test_unknown_transaction_cannot_be_retried(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.UNKNOWN,
    )

    with pytest.raises(
        RecoveryError,
        match="not marked safe to retry",
    ):
        engine.prepare_retry(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_dispatched_transaction_cannot_be_retried(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.DISPATCHED,
    )

    with pytest.raises(RecoveryError):
        engine.prepare_retry(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_success_transaction_cannot_be_retried(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.SUCCESS,
    )

    with pytest.raises(RecoveryError):
        engine.prepare_retry(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


@pytest.mark.parametrize(
    "state",
    [
        TransactionState.CREATED,
        TransactionState.INTENT_VALIDATED,
        TransactionState.MANDATE_VALID,
        TransactionState.POLICY_APPROVED,
        TransactionState.LOCK_ACQUIRED,
        TransactionState.DISPATCHED,
        TransactionState.UNKNOWN,
        TransactionState.RECONCILE_PENDING,
        TransactionState.SUCCESS,
        TransactionState.COMPLETED,
    ],
)
def test_only_safe_retry_state_can_prepare_retry(
    recovery_context,
    state,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=state,
    )

    with pytest.raises(RecoveryError):
        engine.prepare_retry(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


# Refund flow


def test_stockout_starts_refund(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.STOCKOUT_DETECTED,
    )

    original_updated_at = transaction.updated_at

    result = engine.start_refund(transaction)

    assert result.action == "START_REFUND"
    assert (
        result.transaction.state
        == TransactionState.REFUNDING
    )
    assert result.transaction.updated_at >= original_updated_at

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.REFUND_STARTED,
    ]

    assert events[0].state == TransactionState.REFUNDING

    assert events[0].details == {
        "action": "START_REFUND",
    }

    assert audit_trail.verify_chain() is True


def test_refund_cannot_start_from_success(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.SUCCESS,
    )

    with pytest.raises(
        RecoveryError,
        match="requires STOCKOUT_DETECTED",
    ):
        engine.start_refund(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_refund_cannot_start_from_completed(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.COMPLETED,
    )

    with pytest.raises(
        RecoveryError,
        match="requires STOCKOUT_DETECTED",
    ):
        engine.start_refund(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_refund_can_be_marked_refunded(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.REFUNDING,
    )

    original_updated_at = transaction.updated_at

    result = engine.mark_refunded(transaction)

    assert result.action == "REFUND_COMPLETED"
    assert (
        result.transaction.state
        == TransactionState.REFUNDED
    )
    assert result.transaction.updated_at >= original_updated_at

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.REFUND_COMPLETED,
    ]

    assert events[0].state == TransactionState.REFUNDED

    assert events[0].details == {
        "action": "REFUND_COMPLETED",
    }

    assert audit_trail.verify_chain() is True


def test_refund_cannot_be_marked_completed_from_stockout(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.STOCKOUT_DETECTED,
    )

    with pytest.raises(
        RecoveryError,
        match="not currently refunding",
    ):
        engine.mark_refunded(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_refund_cannot_be_marked_completed_from_success(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.SUCCESS,
    )

    with pytest.raises(
        RecoveryError,
        match="not currently refunding",
    ):
        engine.mark_refunded(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


# Reroute flow


def test_reroute_requires_refund(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.REFUNDED,
    )

    original_updated_at = transaction.updated_at

    result = engine.start_reroute(transaction)

    assert result.action == "START_REROUTE"
    assert (
        result.transaction.state
        == TransactionState.REROUTING
    )
    assert result.transaction.updated_at >= original_updated_at

    # No dedicated REROUTE_STARTED audit event exists yet.
    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_reroute_cannot_start_before_refund(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.STOCKOUT_DETECTED,
    )

    with pytest.raises(
        RecoveryError,
        match="requires REFUNDED",
    ):
        engine.start_reroute(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_reroute_cannot_start_from_success(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.SUCCESS,
    )

    with pytest.raises(
        RecoveryError,
        match="requires REFUNDED",
    ):
        engine.start_reroute(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_reroute_can_be_marked_recovered(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.REROUTING,
    )

    original_updated_at = transaction.updated_at

    result = engine.mark_recovered(transaction)

    assert result.action == "TRANSACTION_RECOVERED"
    assert (
        result.transaction.state
        == TransactionState.RECOVERED
    )
    assert result.transaction.updated_at >= original_updated_at

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.RECOVERY_COMPLETED,
    ]

    assert events[0].state == TransactionState.RECOVERED

    assert events[0].details == {
        "action": "TRANSACTION_RECOVERED",
    }

    assert audit_trail.verify_chain() is True


def test_recovery_cannot_be_marked_before_rerouting(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.REFUNDED,
    )

    with pytest.raises(
        RecoveryError,
        match="requires REROUTING",
    ):
        engine.mark_recovered(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


# Final recovery completion


def test_recovered_transaction_can_be_completed(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.RECOVERED,
    )

    original_updated_at = transaction.updated_at

    result = engine.complete_recovery(transaction)

    assert result.action == "RECOVERY_COMPLETED"
    assert (
        result.transaction.state
        == TransactionState.COMPLETED
    )
    assert result.transaction.updated_at >= original_updated_at

    # RECOVERY_COMPLETED is emitted by mark_recovered().
    # complete_recovery() only performs final state completion.
    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_recovery_cannot_be_completed_before_recovered(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.REROUTING,
    )

    with pytest.raises(
        RecoveryError,
        match="must be RECOVERED",
    ):
        engine.complete_recovery(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


def test_completed_transaction_cannot_be_completed_again(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.COMPLETED,
    )

    with pytest.raises(
        RecoveryError,
        match="must be RECOVERED",
    ):
        engine.complete_recovery(transaction)

    assert audit_trail.list_events(
        transaction_id="txn_001"
    ) == []


# Full stockout recovery path

def test_complete_stockout_recovery_flow(
    recovery_context,
):
    engine, audit_trail = recovery_context

    transaction = make_transaction(
        state=TransactionState.STOCKOUT_DETECTED,
    )

    result = engine.start_refund(transaction)

    assert (
        result.transaction.state
        == TransactionState.REFUNDING
    )

    result = engine.mark_refunded(
        result.transaction
    )

    assert (
        result.transaction.state
        == TransactionState.REFUNDED
    )

    result = engine.start_reroute(
        result.transaction
    )

    assert (
        result.transaction.state
        == TransactionState.REROUTING
    )

    result = engine.mark_recovered(
        result.transaction
    )

    assert (
        result.transaction.state
        == TransactionState.RECOVERED
    )

    result = engine.complete_recovery(
        result.transaction
    )

    assert (
        result.transaction.state
        == TransactionState.COMPLETED
    )

    assert result.action == "RECOVERY_COMPLETED"

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.REFUND_STARTED,
        AuditEventType.REFUND_COMPLETED,
        AuditEventType.RECOVERY_COMPLETED,
    ]

    assert [
        event.state
        for event in events
    ] == [
        TransactionState.REFUNDING,
        TransactionState.REFUNDED,
        TransactionState.RECOVERED,
    ]

    assert audit_trail.verify_chain() is True