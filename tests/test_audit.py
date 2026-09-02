from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from engine.audit import AuditTrailError, SQLiteAuditTrail
from models.audit import AuditEventType
from models.transaction import TransactionState


INTENT_HASH = "a" * 64


def make_trail(tmp_path: Path) -> SQLiteAuditTrail:
    return SQLiteAuditTrail(str(tmp_path / "audit.db"))


def append_event(
    trail: SQLiteAuditTrail,
    *,
    event_type: AuditEventType = AuditEventType.INTENT_RECEIVED,
    state: TransactionState = TransactionState.CREATED,
    details: dict[str, object] | None = None,
    event_id: str | None = None,
):
    return trail.append(
        event_type=event_type,
        transaction_id="txn_001",
        intent_id="intent_001",
        user_id="user_123",
        agent_id="agent_001",
        state=state,
        intent_hash=INTENT_HASH,
        details=details,
        event_id=event_id,
    )

def test_append_creates_audit_record_and_genesis_link(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    event = append_event(trail)

    assert event.sequence == 1
    assert event.previous_event_hash == "0" * 64
    assert len(event.event_hash) == 64
    assert trail.verify_chain() is True


def test_second_event_links_to_first(tmp_path: Path):
    trail = make_trail(tmp_path)

    first = append_event(trail)

    second = append_event(
        trail,
        event_type=AuditEventType.INTENT_VALIDATED,
        state=TransactionState.INTENT_VALIDATED,
    )

    assert second.sequence == 2
    assert second.previous_event_hash == first.event_hash
    assert trail.verify_chain() is True


def test_events_are_append_only_and_ordered(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    append_event(trail)

    append_event(
        trail,
        event_type=AuditEventType.POLICY_APPROVED,
        state=TransactionState.POLICY_APPROVED,
    )

    events = trail.list_events()

    assert [event.sequence for event in events] == [1, 2]
    assert [event.event_type for event in events] == [
        AuditEventType.INTENT_RECEIVED,
        AuditEventType.POLICY_APPROVED,
    ]


def test_transaction_filter_returns_only_matching_events(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    append_event(trail)

    trail.append(
        event_type=AuditEventType.INTENT_RECEIVED,
        transaction_id="txn_002",
        intent_id="intent_002",
        user_id="user_123",
        agent_id="agent_001",
        state=TransactionState.CREATED,
        intent_hash="b" * 64,
    )

    events = trail.list_events(
        transaction_id="txn_001"
    )

    assert len(events) == 1
    assert events[0].transaction_id == "txn_001"


def test_details_are_canonicalized_and_preserved(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    event = append_event(
        trail,
        details={
            "reason": "approved",
            "nested": {
                "z": 2,
                "a": 1,
            },
        },
    )

    assert event.details == {
        "reason": "approved",
        "nested": {
            "z": 2,
            "a": 1,
        },
    }

    assert trail.verify_chain() is True


def test_mutating_stored_row_breaks_chain(
    tmp_path: Path,
):
    db_path = tmp_path / "audit.db"
    trail = SQLiteAuditTrail(str(db_path))

    append_event(
        trail,
        details={"reason": "approved"},
    )

    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            "UPDATE audit_events "
            "SET details_json = ? "
            "WHERE sequence = 1",
            ('{"reason":"tampered"}',),
        )
        connection.commit()
    finally:
        connection.close()

    assert trail.verify_chain() is False


def test_event_id_is_unique(tmp_path: Path):
    trail = make_trail(tmp_path)
    event_id = "event_001"

    append_event(
        trail,
        event_id=event_id,
    )

    with pytest.raises(AuditTrailError):
        trail.append(
            event_type=AuditEventType.INTENT_VALIDATED,
            transaction_id="txn_001",
            intent_id="intent_001",
            user_id="user_123",
            agent_id="agent_001",
            state=TransactionState.INTENT_VALIDATED,
            intent_hash=INTENT_HASH,
            event_id=event_id,
        )


def test_non_json_serializable_details_are_rejected(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    with pytest.raises(AuditTrailError):
        append_event(
            trail,
            details={"bad": object()},
        )


def test_get_event_returns_event_by_id(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    event = append_event(
        trail,
        event_type=AuditEventType.INTENT_VALIDATED,
        state=TransactionState.INTENT_VALIDATED,
    )

    result = trail.get_event(
        event_id=event.event_id
    )

    assert result == event


def test_get_event_returns_none_for_unknown_id(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    assert trail.get_event(
        event_id="missing"
    ) is None


def test_none_intent_hash_round_trips_and_verifies(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    event = trail.append(
        event_type=AuditEventType.INTENT_RECEIVED,
        transaction_id="txn_001",
        intent_id="intent_001",
        user_id="user_123",
        agent_id="agent_001",
        state=TransactionState.CREATED,
        intent_hash=None,
    )

    assert event.intent_hash is None
    assert trail.verify_chain() is True

    stored = trail.get_event(
        event_id=event.event_id
    )

    assert stored is not None
    assert stored.intent_hash is None


def test_hash_chain_is_global_across_transactions(
    tmp_path: Path,
):
    trail = make_trail(tmp_path)

    first = append_event(trail)

    second = trail.append(
        event_type=AuditEventType.INTENT_RECEIVED,
        transaction_id="txn_002",
        intent_id="intent_002",
        user_id="user_123",
        agent_id="agent_001",
        state=TransactionState.CREATED,
        intent_hash="b" * 64,
    )

    assert second.sequence == 2
    assert second.previous_event_hash == first.event_hash

    txn_001_events = trail.list_events(
        transaction_id="txn_001"
    )

    assert len(txn_001_events) == 1
    assert txn_001_events[0].sequence == 1

    assert trail.verify_chain() is True