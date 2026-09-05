from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from models.telemetry import (
    WebhookTelemetryEvent,
    WebhookTelemetryEventType,
)


class WebhookTelemetryStore:
    """
    Persistent SQLite store for webhook delivery telemetry.

    Telemetry is observational only. It is deliberately separate from
    execution idempotency and the financial audit trail.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path)
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
                CREATE TABLE IF NOT EXISTS webhook_telemetry (
                    telemetry_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    webhook_event_id TEXT NOT NULL,
                    transaction_id TEXT,
                    payment_id TEXT,
                    order_id TEXT,
                    details_json TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_webhook_telemetry_event_id
                ON webhook_telemetry(webhook_event_id)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_webhook_telemetry_transaction_id
                ON webhook_telemetry(transaction_id)
                """
            )

            connection.commit()

    def append(
        self,
        event: WebhookTelemetryEvent,
    ) -> WebhookTelemetryEvent:
        payload = json.dumps(
            event.details,
            sort_keys=True,
            separators=(",", ":"),
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO webhook_telemetry (
                    telemetry_id,
                    event_type,
                    occurred_at,
                    webhook_event_id,
                    transaction_id,
                    payment_id,
                    order_id,
                    details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.telemetry_id,
                    event.event_type.value,
                    event.occurred_at.isoformat(),
                    event.webhook_event_id,
                    event.transaction_id,
                    event.payment_id,
                    event.order_id,
                    payload,
                ),
            )

            connection.commit()

        return event

    def list_events(
        self,
        *,
        transaction_id: str | None = None,
        webhook_event_id: str | None = None,
    ) -> list[WebhookTelemetryEvent]:
        query = """
            SELECT
                telemetry_id,
                event_type,
                occurred_at,
                webhook_event_id,
                transaction_id,
                payment_id,
                order_id,
                details_json
            FROM webhook_telemetry
        """

        conditions: list[str] = []
        parameters: list[str] = []

        if transaction_id is not None:
            conditions.append(
                "transaction_id = ?"
            )
            parameters.append(transaction_id)

        if webhook_event_id is not None:
            conditions.append(
                "webhook_event_id = ?"
            )
            parameters.append(webhook_event_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += """
            ORDER BY occurred_at ASC, telemetry_id ASC
        """

        with self._connect() as connection:
            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return [
            WebhookTelemetryEvent(
                telemetry_id=row[0],
                event_type=WebhookTelemetryEventType(
                    row[1]
                ),
                occurred_at=datetime.fromisoformat(row[2]),
                webhook_event_id=row[3],
                transaction_id=row[4],
                payment_id=row[5],
                order_id=row[6],
                details=json.loads(row[7]),
            )
            for row in rows
        ]

    def count(
        self,
        event_type: WebhookTelemetryEventType | None = None,
    ) -> int:
        if event_type is None:
            query = """
                SELECT COUNT(*)
                FROM webhook_telemetry
            """
            parameters: tuple[object, ...] = ()
        else:
            query = """
                SELECT COUNT(*)
                FROM webhook_telemetry
                WHERE event_type = ?
            """
            parameters = (event_type.value,)

        with self._connect() as connection:
            row = connection.execute(
                query,
                parameters,
            ).fetchone()

        return int(row[0])
