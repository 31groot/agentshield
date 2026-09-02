import pytest

from engine.state_machine import (
    InvalidTransactionTransition,
    TransactionStateMachine,
)
from models.transaction import TransactionState


@pytest.fixture
def machine() -> TransactionStateMachine:
    return TransactionStateMachine()


def test_happy_path_transitions(machine):
    state = TransactionState.CREATED

    state = machine.transition(
        state,
        TransactionState.INTENT_VALIDATED,
    )

    state = machine.transition(
        state,
        TransactionState.POLICY_APPROVED,
    )

    state = machine.transition(
        state,
        TransactionState.MANDATE_VALID,
    )

    state = machine.transition(
        state,
        TransactionState.LOCK_ACQUIRED,
    )

    state = machine.transition(
        state,
        TransactionState.DISPATCHED,
    )

    state = machine.transition(
        state,
        TransactionState.SUCCESS,
    )

    state = machine.transition(
        state,
        TransactionState.COMPLETED,
    )

    assert state == TransactionState.COMPLETED


def test_dispatched_can_become_unknown(machine):
    state = machine.transition(
        TransactionState.DISPATCHED,
        TransactionState.UNKNOWN,
    )

    assert state == TransactionState.UNKNOWN


def test_unknown_requires_reconciliation(machine):
    state = machine.transition(
        TransactionState.UNKNOWN,
        TransactionState.RECONCILE_PENDING,
    )

    assert state == TransactionState.RECONCILE_PENDING


def test_reconciliation_can_resolve_to_success(machine):
    state = machine.transition(
        TransactionState.RECONCILE_PENDING,
        TransactionState.SUCCESS,
    )

    assert state == TransactionState.SUCCESS


def test_reconciliation_can_resolve_to_safe_retry(machine):
    state = machine.transition(
        TransactionState.RECONCILE_PENDING,
        TransactionState.FAILED_SAFE_TO_RETRY,
    )

    assert state == TransactionState.FAILED_SAFE_TO_RETRY


def test_safe_retry_returns_to_lock_acquisition(machine):
    state = machine.transition(
        TransactionState.FAILED_SAFE_TO_RETRY,
        TransactionState.LOCK_ACQUIRED,
    )

    assert state == TransactionState.LOCK_ACQUIRED


def test_stockout_recovery_path(machine):
    state = machine.transition(
        TransactionState.SUCCESS,
        TransactionState.STOCKOUT_DETECTED,
    )

    state = machine.transition(
        state,
        TransactionState.REFUNDING,
    )

    state = machine.transition(
        state,
        TransactionState.REFUNDED,
    )

    state = machine.transition(
        state,
        TransactionState.REROUTING,
    )

    state = machine.transition(
        state,
        TransactionState.RECOVERED,
    )

    state = machine.transition(
        state,
        TransactionState.COMPLETED,
    )

    assert state == TransactionState.COMPLETED


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (
            TransactionState.CREATED,
            TransactionState.SUCCESS,
        ),
        (
            TransactionState.CREATED,
            TransactionState.DISPATCHED,
        ),
        (
            TransactionState.MANDATE_VALID,
            TransactionState.COMPLETED,
        ),
        (
            TransactionState.POLICY_APPROVED,
            TransactionState.SUCCESS,
        ),
        (
            TransactionState.DISPATCHED,
            TransactionState.COMPLETED,
        ),
        (
            TransactionState.UNKNOWN,
            TransactionState.SUCCESS,
        ),
        (
            TransactionState.COMPLETED,
            TransactionState.DISPATCHED,
        ),
    ],
)
def test_invalid_transitions_are_rejected(
    machine,
    current,
    target,
):
    with pytest.raises(InvalidTransactionTransition):
        machine.transition(current, target)


def test_completed_is_terminal(machine):
    assert machine.can_transition(
        TransactionState.COMPLETED,
        TransactionState.COMPLETED,
    ) is False


def test_same_state_is_not_a_valid_transition(machine):
    assert machine.can_transition(
        TransactionState.CREATED,
        TransactionState.CREATED,
    ) is False