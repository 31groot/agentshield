from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from models.audit import AuditEvent, AuditEventType
from models.transaction import TransactionState


class AuditTrailError(Exception):
    """Raised when the append-only audit trail cannot safely continue."""


class SQLiteAuditTrail:
    """
    Append-only, hash-chained audit trail backed by SQLite WAL.

    """

    _GENESIS_HASH = "0" * 64

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()

        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    intent_hash TEXT,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    previous_event_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                )
                """
            )

            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_transaction "
                "ON audit_events(transaction_id, sequence)"
            )
        finally:
            connection.close()

    def append(
        self,
        *,
        event_type: AuditEventType,
        transaction_id: str,
        intent_id: str,
        user_id: str,
        agent_id: str,
        state: TransactionState,
        intent_hash: str | None,
        details: dict[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        """Atomically append one new audit record."""

        timestamp = occurred_at or datetime.now(timezone.utc)
        resolved_event_id = event_id or str(uuid4())
        resolved_details = dict(details or {})

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                "SELECT sequence, event_hash FROM audit_events "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()

            if row is None:
                previous_hash = self._GENESIS_HASH
                sequence = 1
            else:
                previous_hash = str(row["event_hash"])
                sequence = int(row["sequence"]) + 1

            payload = {
                "sequence": sequence,
                "event_id": resolved_event_id,
                "event_type": event_type.value,
                "transaction_id": transaction_id,
                "intent_id": intent_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "state": state.value,
                "intent_hash": intent_hash,
                "occurred_at": timestamp.astimezone(timezone.utc).isoformat(),
                "details": self._canonical_details(resolved_details),
                "previous_event_hash": previous_hash,
            }

            event_hash = hashlib.sha256(
                self._canonical_json(payload).encode("utf-8")
            ).hexdigest()

            connection.execute(
                """
                INSERT INTO audit_events (
                    sequence,
                    event_id,
                    event_type,
                    transaction_id,
                    intent_id,
                    user_id,
                    agent_id,
                    state,
                    intent_hash,
                    occurred_at,
                    details_json,
                    previous_event_hash,
                    event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    resolved_event_id,
                    event_type.value,
                    transaction_id,
                    intent_id,
                    user_id,
                    agent_id,
                    state.value,
                    intent_hash,
                    payload["occurred_at"],
                    self._canonical_json(resolved_details),
                    previous_hash,
                    event_hash,
                ),
            )

            connection.execute("COMMIT")

            return AuditEvent(
                sequence=sequence,
                event_id=resolved_event_id,
                event_type=event_type,
                transaction_id=transaction_id,
                intent_id=intent_id,
                user_id=user_id,
                agent_id=agent_id,
                state=state,
                intent_hash=intent_hash,
                occurred_at=datetime.fromisoformat(
                    payload["occurred_at"]
                ),
                details=resolved_details,
                previous_event_hash=previous_hash,
                event_hash=event_hash,
            )

        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            if isinstance(exc, AuditTrailError):
                raise

            raise AuditTrailError(
                "Failed to append audit record"
            ) from exc

        finally:
            connection.close()

    def list_events(
        self,
        *,
        transaction_id: str | None = None,
    ) -> list[AuditEvent]:
        """Read audit events in immutable append order."""

        connection = self._connect()

        try:
            if transaction_id is None:
                rows = connection.execute(
                    "SELECT * FROM audit_events ORDER BY sequence"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM audit_events "
                    "WHERE transaction_id = ? ORDER BY sequence",
                    (transaction_id,),
                ).fetchall()

            return [self._row_to_event(row) for row in rows]

        finally:
            connection.close()

    def get_event(
        self,
        *,
        event_id: str,
    ) -> AuditEvent | None:
        """Return one immutable audit event by event ID."""

        connection = self._connect()

        try:
            row = connection.execute(
                "SELECT * FROM audit_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_event(row)

        finally:
            connection.close()

    def verify_chain(self) -> bool:
        """Verify ordering, links, and hashes across the full audit trail."""

        connection = self._connect()

        try:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY sequence"
            ).fetchall()
        finally:
            connection.close()

        previous_hash = self._GENESIS_HASH
        expected_sequence = 1

        for row in rows:
            if int(row["sequence"]) != expected_sequence:
                return False

            if str(row["previous_event_hash"]) != previous_hash:
                return False

            try:
                details = json.loads(str(row["details_json"]))
            except json.JSONDecodeError:
                return False

            payload = {
                "sequence": int(row["sequence"]),
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "transaction_id": str(row["transaction_id"]),
                "intent_id": str(row["intent_id"]),
                "user_id": str(row["user_id"]),
                "agent_id": str(row["agent_id"]),
                "state": str(row["state"]),
                "intent_hash": row["intent_hash"],
                "occurred_at": str(row["occurred_at"]),
                "details": self._canonical_details(details),
                "previous_event_hash": previous_hash,
            }

            expected_hash = hashlib.sha256(
                self._canonical_json(payload).encode("utf-8")
            ).hexdigest()

            if str(row["event_hash"]) != expected_hash:
                return False

            previous_hash = expected_hash
            expected_sequence += 1

        return True

    @staticmethod
    def _canonical_details(
        details: dict[str, Any],
    ) -> dict[str, Any]:
        # JSON round-trip normalizes nested data into deterministic
        try:
            return json.loads(
                json.dumps(
                    details,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise AuditTrailError(
                "Audit details must be JSON serializable"
            ) from exc

    @staticmethod
    def _canonical_json(
        payload: dict[str, Any],
    ) -> str:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _row_to_event(
        row: sqlite3.Row,
    ) -> AuditEvent:
        return AuditEvent(
            sequence=int(row["sequence"]),
            event_id=str(row["event_id"]),
            event_type=AuditEventType(str(row["event_type"])),
            transaction_id=str(row["transaction_id"]),
            intent_id=str(row["intent_id"]),
            user_id=str(row["user_id"]),
            agent_id=str(row["agent_id"]),
            state=TransactionState(str(row["state"])),
            intent_hash=(
                str(row["intent_hash"])
                if row["intent_hash"] is not None
                else None
            ),
            occurred_at=datetime.fromisoformat(
                str(row["occurred_at"])
            ),
            details=json.loads(str(row["details_json"])),
            previous_event_hash=str(
                row["previous_event_hash"]
            ),
            event_hash=str(row["event_hash"]),
        )