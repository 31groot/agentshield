from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from engine.audit import SQLiteAuditTrail
from engine.state_machine import (
    InvalidTransactionTransition,
    TransactionStateMachine,
)
from engine.transaction_store import SQLiteTransactionStore
from models.audit import AuditEventType
from models.recovery import RecoveryResult
from models.transaction import (
    TransactionRecord,
    TransactionState,
)


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
    - persist successful state transitions
    - append immutable audit evidence for successful recovery actions
    """

    RETRY_ACTION: ClassVar[str] = "RETRY_EXECUTION"
    REFUND_ACTION: ClassVar[str] = "START_REFUND"
    REFUND_COMPLETED_ACTION: ClassVar[str] = "REFUND_COMPLETED"
    REROUTE_ACTION: ClassVar[str] = "START_REROUTE"
    RECOVERED_ACTION: ClassVar[str] = "TRANSACTION_RECOVERED"
    RECOVERY_COMPLETED_ACTION: ClassVar[str] = "RECOVERY_COMPLETED"

    def __init__(
        self,
        audit_trail: SQLiteAuditTrail,
        transaction_store: SQLiteTransactionStore,
        state_machine: type[
            TransactionStateMachine
        ] = TransactionStateMachine,
    ) -> None:
        self._audit_trail = audit_trail
        self._transaction_store = transaction_store
        self._state_machine = state_machine

    def _persist(self, transaction: TransactionRecord) -> None:
        try:
            self._transaction_store.update(transaction)
        except Exception as exc:
            raise RecoveryError(
                "Recovery state could not be persisted"
            ) from exc

    def _audit(
        self,
        *,
        event_type: AuditEventType,
        transaction: TransactionRecord,
        details: dict[str, object] | None = None,
    ) -> None:
        self._audit_trail.append(
            event_type=event_type,
            transaction_id=transaction.transaction_id,
            intent_id=transaction.intent_id,
            user_id=transaction.user_id,
            agent_id=transaction.agent_id,
            state=transaction.state,
            intent_hash=transaction.intent_hash,
            details=details,
        )

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

        self._persist(updated)

        self._audit(
            event_type=AuditEventType.RECOVERY_STARTED,
            transaction=updated,
            details={
                "action": self.RETRY_ACTION,
            },
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

        self._persist(updated)

        self._audit(
            event_type=AuditEventType.REFUND_STARTED,
            transaction=updated,
            details={
                "action": self.REFUND_ACTION,
            },
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

        self._persist(updated)

        self._audit(
            event_type=AuditEventType.REFUND_COMPLETED,
            transaction=updated,
            details={
                "action": self.REFUND_COMPLETED_ACTION,
            },
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

        self._persist(updated)

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

        self._persist(updated)

        self._audit(
            event_type=AuditEventType.RECOVERY_COMPLETED,
            transaction=updated,
            details={
                "action": self.RECOVERED_ACTION,
            },
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

        self._persist(updated)

        return RecoveryResult(
            transaction=updated,
            action=self.RECOVERY_COMPLETED_ACTION,
        )
