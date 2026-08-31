from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models.transaction import IdempotencyRecord, IdempotencyStatus


class WALIdempotencyStore:
    """
    SQLite-backed idempotency store.

    Guarantees:
    - SQLite WAL mode is enabled.
    - idempotency_key is unique.
    - only one concurrent request can acquire a new key.
    - duplicate requests are detected by the database.

    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        """
        Open a SQLite connection configured for AgentShield.

        WAL mode improves concurrent read/write behavior.
        """
        connection = sqlite3.connect(
            self._db_path,
            timeout=10.0,
        )

        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")

        return connection

    def _initialize_database(self) -> None:
        """
        Create the idempotency ledger if it does not already exist.
        """
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_ledger (
                    idempotency_key TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def acquire(
        self,
        *,
        idempotency_key: str,
        transaction_id: str,
    ) -> bool:
        """
        Atomically acquire an idempotency key.

        Returns:
            True:
                This request successfully claimed the key.

            False:
                The key already exists and belongs to an existing
                execution attempt.

        The database PRIMARY KEY is the concurrency authority.
        There is intentionally no separate "check then insert".
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        if not transaction_id.strip():
            raise ValueError("transaction_id cannot be empty")

        created_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO idempotency_ledger (
                    idempotency_key,
                    transaction_id,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    transaction_id,
                    IdempotencyStatus.ACQUIRED.value,
                    created_at,
                ),
            )

            connection.commit()

            return cursor.rowcount == 1

    def get(
        self,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        """
        Retrieve an existing idempotency record.
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    idempotency_key,
                    transaction_id,
                    status,
                    created_at
                FROM idempotency_ledger
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()

        if row is None:
            return None

        return IdempotencyRecord(
            idempotency_key=row[0],
            transaction_id=row[1],
            status=IdempotencyStatus(row[2]),
            created_at=datetime.fromisoformat(row[3]),
        )

    def mark_completed(
        self,
        *,
        idempotency_key: str,
    ) -> bool:
        """
        Mark an existing execution record as completed.

        Returns:
            True  -> a record was updated.
            False -> no record exists for the supplied key.
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE idempotency_ledger
                SET status = ?
                WHERE idempotency_key = ?
                """,
                (
                    IdempotencyStatus.COMPLETED.value,
                    idempotency_key,
                ),
            )

            connection.commit()

            return cursor.rowcount == 1

    def mark_failed_safe_to_retry(
        self,
        *,
        idempotency_key: str,
    ) -> bool:
        """
        Mark an existing execution record as safely retryable.

        """

        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE idempotency_ledger
                SET status = ?
                WHERE idempotency_key = ?
                """,
                (
                    IdempotencyStatus.FAILED_SAFE_TO_RETRY.value,
                    idempotency_key,
                ),
            )

            connection.commit()

            return cursor.rowcount == 1