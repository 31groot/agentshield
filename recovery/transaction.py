from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from engine.state_machine import (
    InvalidTransactionTransition,
    TransactionStateMachine,
)
from models.transaction import (
    TransactionRecord,
    TransactionState,
)
from models.recovery import RecoveryResult

class RecoveryError(Exception):
    """
    Raised when a recovery operation cannot be performed safely.
    """
class TransactionRecoveryEngine:
    """
    Deterministic recovery engine for AgentShield transactions.

    Responsibilities:
    - permit only safe retry paths
    - initiate fulfillment recovery transitions
    - reject unsafe blind retries
    - use the transaction state machine as the source of truth

    This class does not:
    - call Claude
    - call Razorpay
    - perform refunds
    - perform rerouting
    - make policy decisions
    """

    RETRY_ACTION: ClassVar[str] = "RETRY_EXECUTION"

    REFUND_ACTION: ClassVar[str] = "START_REFUND"

    REFUND_COMPLETED_ACTION: ClassVar[str] = "REFUND_COMPLETED"

    REROUTE_ACTION: ClassVar[str] = "START_REROUTE"

    RECOVERED_ACTION: ClassVar[str] = "TRANSACTION_RECOVERED"

    RECOVERY_COMPLETED_ACTION: ClassVar[str] = "RECOVERY_COMPLETED"

    def __init__(
        self,
        state_machine: type[
            TransactionStateMachine
        ] = TransactionStateMachine,
    ) -> None:
        self._state_machine = state_machine

    def prepare_retry(
        self,
        transaction: TransactionRecord,
    ) -> RecoveryResult:
        """
        Prepare a transaction for a new execution attempt.

        Only FAILED_SAFE_TO_RETRY is eligible.

        UNKNOWN is explicitly rejected because the external payment
        result has not been established yet.
        """

        if transaction.state != TransactionState.FAILED_SAFE_TO_RETRY:
            raise RecoveryError(
                "Transaction is not marked safe to retry: "
                f"{transaction.state.value}"
            )

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                TransactionState.LOCK_ACQUIRED,
            )
        except InvalidTransactionTransition as exc:
            raise RecoveryError(
                "Safe retry transition is not permitted"
            ) from exc

        updated = transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        return RecoveryResult(
            transaction=updated,
            action=self.RETRY_ACTION,
        )

    def start_refund(
        self,
        transaction: TransactionRecord,
    ) -> RecoveryResult:
        """
        Move a transaction with a fulfillment problem
        into the refunding workflow.
        """

        if transaction.state != TransactionState.STOCKOUT_DETECTED:
            raise RecoveryError(
                "Refund recovery requires STOCKOUT_DETECTED state: "
                f"{transaction.state.value}"
            )

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                TransactionState.REFUNDING,
            )
        except InvalidTransactionTransition as exc:
            raise RecoveryError(
                "Refund transition is not permitted"
            ) from exc

        updated = transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        return RecoveryResult(
            transaction=updated,
            action=self.REFUND_ACTION,
        )

    def mark_refunded(
        self,
        transaction: TransactionRecord,
    ) -> RecoveryResult:
        """
        Record that the refund operation completed successfully.
        """

        if transaction.state != TransactionState.REFUNDING:
            raise RecoveryError(
                "Transaction is not currently refunding: "
                f"{transaction.state.value}"
            )

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                TransactionState.REFUNDED,
            )
        except InvalidTransactionTransition as exc:
            raise RecoveryError(
                "Refund completion transition is not permitted"
            ) from exc

        updated = transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        return RecoveryResult(
            transaction=updated,
            action=self.REFUND_COMPLETED_ACTION,
        )

    def start_reroute(
        self,
        transaction: TransactionRecord,
    ) -> RecoveryResult:
        """
        Begin rerouting after a successful refund.
        """

        if transaction.state != TransactionState.REFUNDED:
            raise RecoveryError(
                "Rerouting requires REFUNDED state: "
                f"{transaction.state.value}"
            )

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                TransactionState.REROUTING,
            )
        except InvalidTransactionTransition as exc:
            raise RecoveryError(
                "Reroute transition is not permitted"
            ) from exc

        updated = transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        return RecoveryResult(
            transaction=updated,
            action=self.REROUTE_ACTION,
        )

    def mark_recovered(
        self,
        transaction: TransactionRecord,
    ) -> RecoveryResult:
        """
        Record successful fulfillment recovery.
        """

        if transaction.state != TransactionState.REROUTING:
            raise RecoveryError(
                "Recovery completion requires REROUTING state: "
                f"{transaction.state.value}"
            )

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                TransactionState.RECOVERED,
            )
        except InvalidTransactionTransition as exc:
            raise RecoveryError(
                "Recovery completion transition is not permitted"
            ) from exc

        updated = transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        return RecoveryResult(
            transaction=updated,
            action=self.RECOVERED_ACTION,
        )

    def complete_recovery(
        self,
        transaction: TransactionRecord,
    ) -> RecoveryResult:
        """
        Move a successfully recovered transaction to COMPLETED.
        """

        if transaction.state != TransactionState.RECOVERED:
            raise RecoveryError(
                "Transaction must be RECOVERED before completion: "
                f"{transaction.state.value}"
            )

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                TransactionState.COMPLETED,
            )
        except InvalidTransactionTransition as exc:
            raise RecoveryError(
                "Recovery completion transition is not permitted"
            ) from exc

        updated = transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        return RecoveryResult(
            transaction=updated,
            action=self.RECOVERY_COMPLETED_ACTION,
        )