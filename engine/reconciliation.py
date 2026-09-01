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
    WebhookEventRecord,
    WebhookProcessingStatus,
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
                    event_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    processed_at TEXT
                )
                """
            )

            connection.commit()


    def receive(self, event_id: str) -> bool:
        """
        Register a webhook for processing.

        Returns:
            True  -> event was newly received.
            False -> event already exists.
        """
        if not event_id.strip():
            raise ValueError("event_id cannot be empty")

        received_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_event_ledger (
                    event_id,
                    status,
                    received_at,
                    processed_at
                )
                VALUES (?, ?, ?, NULL)
                """,
                (
                    event_id,
                    WebhookProcessingStatus.RECEIVED.value,
                    received_at,
                ),
            )

            connection.commit()

            return cursor.rowcount == 1

    def get(
        self,
        event_id: str,
    ) -> WebhookEventRecord | None:
        if not event_id.strip():
            raise ValueError("event_id cannot be empty")

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    event_id,
                    status,
                    received_at,
                    processed_at
                FROM webhook_event_ledger
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()

        if row is None:
            return None

        return WebhookEventRecord(
            event_id=row[0],
            status=WebhookProcessingStatus(row[1]),
            received_at=datetime.fromisoformat(row[2]),
            processed_at=(
                datetime.fromisoformat(row[3])
                if row[3] is not None
                else None
            ),
        )

    def mark_processed(self, event_id: str) -> bool:
        if not event_id.strip():
            raise ValueError("event_id cannot be empty")

        processed_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE webhook_event_ledger
                SET
                    status = ?,
                    processed_at = ?
                WHERE
                    event_id = ?
                    AND status = ?
                """,
                (
                    WebhookProcessingStatus.PROCESSED.value,
                    processed_at,
                    event_id,
                    WebhookProcessingStatus.RECEIVED.value,
                ),
            )

            connection.commit()

            return cursor.rowcount == 1


    def mark_rejected(self, event_id: str) -> bool:
        if not event_id.strip():
            raise ValueError("event_id cannot be empty")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE webhook_event_ledger
                SET status = ?
                WHERE event_id = ?
            """,
                (
                    WebhookProcessingStatus.REJECTED.value,
                    event_id,
                ),
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

        existing = self._webhook_store.get(
            event.event_id
        )

        if existing is not None:
            if existing.status == WebhookProcessingStatus.PROCESSED:
                return transaction

            if existing.status == WebhookProcessingStatus.REJECTED:
                return transaction

            # RECEIVED means a previous attempt did not finish.
            # Allow processing to continue.
        else:
            self._webhook_store.receive(
                event.event_id
            )
            
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


        updated_transaction = transaction.model_copy(
            update={
                "state": next_state,
                "razorpay_payment_id": event.payment_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        self._webhook_store.mark_processed(
            event.event_id
        )

        return updated_transaction


