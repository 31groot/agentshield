from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from engine.state_machine import (
    InvalidTransactionTransition,
    TransactionStateMachine,
)

from models.transaction import (
    TransactionRecord,
    TransactionState,
)

from models.webhook import (
    WebhookEvent,
    WebhookEventType,
)


class ReconciliationError(Exception):
    """
    Raised when a verified webhook cannot safely reconcile
    with the current AgentShield transaction.
    """


class WebhookEventStore:
    """
    Persistent SQLite-backed webhook deduplication store.

    A webhook event ID is processed at most once.

    This ledger is deliberately separate from payment execution
    idempotency because webhook delivery identity and execution
    identity represent different things.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path,
            timeout=10.0,
        )

        connection.execute(
            "PRAGMA journal_mode=WAL;"
        )

        connection.execute(
            "PRAGMA foreign_keys=ON;"
        )

        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_event_ledger (
                    event_id TEXT PRIMARY KEY
                )
                """
            )

            connection.commit()

    def claim(self, event_id: str) -> bool:
        """
        Atomically claim a webhook event.

        Returns:
            True  -> first processing attempt.
            False -> duplicate event.
        """

        if not event_id.strip():
            raise ValueError(
                "event_id cannot be empty"
            )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_event_ledger (
                    event_id
                )
                VALUES (?)
                """,
                (event_id,),
            )

            connection.commit()

            return cursor.rowcount == 1


class ReconciliationEngine:
    """
    Deterministic reconciliation engine.

    Responsibilities:
    - correlate verified webhook evidence with a transaction
    - deduplicate webhook events
    - resolve transaction state through the state machine
    """

    def __init__(
        self,
        webhook_store: WebhookEventStore,
        state_machine: type[
            TransactionStateMachine
        ] = TransactionStateMachine,
    ) -> None:
        self._webhook_store = webhook_store
        self._state_machine = state_machine

    def reconcile(
        self,
        *,
        transaction: TransactionRecord,
        event: WebhookEvent,
    ) -> TransactionRecord:
        """
        Reconcile one verified webhook against one transaction.
        """

        
        # 1. Correlate webhook with transaction

        if event.order_id is not None:
            if transaction.razorpay_order_id is None:
                raise ReconciliationError(
                    "Transaction has no Razorpay order ID"
                )

            if event.order_id != transaction.razorpay_order_id:
                raise ReconciliationError(
                    "Webhook order does not match transaction"
                )

        if event.amount_paise != transaction.amount_paise:
            raise ReconciliationError(
                "Webhook amount does not match transaction"
            )

        if event.currency != transaction.currency:
            raise ReconciliationError(
                "Webhook currency does not match transaction"
            )

        if (
            transaction.razorpay_payment_id is not None
            and event.payment_id
            != transaction.razorpay_payment_id
        ):
            raise ReconciliationError(
                "Webhook payment does not match transaction"
            )

        # 2. Webhook deduplication

        claimed = self._webhook_store.claim(
            event.event_id
        )

        if not claimed:
            return transaction

        # 3. Establish reconciliation state
    

        current_state = transaction.state

        try:
            if current_state == TransactionState.DISPATCHED:
                current_state = self._state_machine.transition(
                    current_state,
                    TransactionState.UNKNOWN,
                )

            if current_state == TransactionState.UNKNOWN:
                current_state = self._state_machine.transition(
                    current_state,
                    TransactionState.RECONCILE_PENDING,
                )

        except InvalidTransactionTransition as exc:
            raise ReconciliationError(
                "Transaction cannot enter reconciliation: "
                f"{transaction.state.value}"
            ) from exc

        # 4. Resolve external payment result

        if (
            event.event_type
            == WebhookEventType.PAYMENT_CAPTURED
        ):
            try:
                next_state = self._state_machine.transition(
                    current_state,
                    TransactionState.SUCCESS,
                )
            except InvalidTransactionTransition as exc:
                raise ReconciliationError(
                    "Captured payment cannot be applied to transaction "
                    f"state {current_state.value}"
                ) from exc

        elif (
            event.event_type
            == WebhookEventType.PAYMENT_FAILED
        ):
            try:
                next_state = self._state_machine.transition(
                    current_state,
                    TransactionState.FAILED_SAFE_TO_RETRY,
                )
            except InvalidTransactionTransition as exc:
                raise ReconciliationError(
                    "Failed payment cannot be applied to transaction "
                    f"state {current_state.value}"
                ) from exc

        else:
            raise ReconciliationError(
                "Unsupported reconciliation event: "
                f"{event.event_type.value}"
            )

        # 5. Return updated transaction


        return transaction.model_copy(
            update={
                "state": next_state,
                "razorpay_payment_id": event.payment_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )