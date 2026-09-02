from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from models.authorization import (
    AgentAuthorization,
    AuthorizationDecision,
)
from models.intent import IntentProposal


class AuthorizationError(Exception):
    """Raised when authorization state cannot be safely accessed."""


class AuthorizationEngine:
    """
    Deterministic verifier for a stored agent authorization.

    This class does not create, mutate, or persist authorization records.
    It only verifies whether a supplied authorization is currently valid
    for a proposed action.
    """

    def verify(
        self,
        proposal: IntentProposal,
        authorization: AgentAuthorization,
    ) -> AuthorizationDecision:
        """
        Verify the identity relationship and lifecycle state of the
        stored authorization.
        """
        
        # 1. Explicit revocation takes precedence over inactivity.
        if authorization.revoked:
            return AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_REVOKED",
                authorization_id=authorization.authorization_id,
            )

        # 2. Authorization must be active.
        if not authorization.active:
            return AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_INACTIVE",
                authorization_id=authorization.authorization_id,
            )

        
        # 3. Authorization must not be expired.
        now = datetime.now(timezone.utc)

        if (
            authorization.expires_at is not None
            and now >= authorization.expires_at
        ):
            return AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_EXPIRED",
                authorization_id=authorization.authorization_id,
            )

        # 4. User must match.
        if proposal.user_id != authorization.user_id:
            return AuthorizationDecision(
                allowed=False,
                reason="USER_MISMATCH",
                authorization_id=authorization.authorization_id,
            )

        # 5. Agent must match.
        if proposal.agent_id != authorization.agent_id:
            return AuthorizationDecision(
                allowed=False,
                reason="AGENT_MISMATCH",
                authorization_id=authorization.authorization_id,
            )

        return AuthorizationDecision(
            allowed=True,
            reason="AUTHORIZATION_APPROVED",
            authorization_id=authorization.authorization_id,
        )


class SQLiteAuthorizationAuthority:
    """
    Server-owned persistent authorization authority.

    Authorization records are stored in SQLite using WAL mode.
    The authority owns creation, lookup, revocation, and deactivation.
    """

    def __init__(self, db_path: str) -> None:
        if not db_path or not db_path.strip():
            raise ValueError("db_path cannot be empty")

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
                CREATE TABLE IF NOT EXISTS authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    revoked INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_authorizations_user_agent
                ON authorizations(user_id, agent_id)
                """
            )
        finally:
            connection.close()

    def create(
        self,
        authorization: AgentAuthorization,
    ) -> AgentAuthorization:
        """
        Persist a new authorization record.

        Authorization IDs are unique and cannot be silently overwritten.
        """

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            connection.execute(
                """
                INSERT INTO authorizations (
                    authorization_id,
                    user_id,
                    agent_id,
                    active,
                    revoked,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    authorization.authorization_id,
                    authorization.user_id,
                    authorization.agent_id,
                    int(authorization.active),
                    int(authorization.revoked),
                    authorization.created_at.astimezone(
                        timezone.utc
                    ).isoformat(),
                    (
                        authorization.expires_at.astimezone(
                            timezone.utc
                        ).isoformat()
                        if authorization.expires_at is not None
                        else None
                    ),
                ),
            )

            connection.execute("COMMIT")
            return authorization

        except sqlite3.IntegrityError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise AuthorizationError(
                "Authorization already exists"
            ) from exc

        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise AuthorizationError(
                "Failed to create authorization"
            ) from exc

        finally:
            connection.close()

    def get(
        self,
        authorization_id: str,
    ) -> AgentAuthorization | None:
        """
        Return one authorization by its server-owned ID.
        """

        if not authorization_id:
            raise ValueError("authorization_id cannot be empty")

        connection = self._connect()

        try:
            row = connection.execute(
                """
                SELECT
                    authorization_id,
                    user_id,
                    agent_id,
                    active,
                    revoked,
                    created_at,
                    expires_at
                FROM authorizations
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_model(row)

        except Exception as exc:
            raise AuthorizationError(
                "Failed to read authorization"
            ) from exc

        finally:
            connection.close()

    def find_for_agent(
        self,
        *,
        user_id: str,
        agent_id: str,
    ) -> list[AgentAuthorization]:
        """
        Return all authorizations for a user/agent pair.

        The authority does not automatically discard revoked or expired
        records. They remain available for audit/history.
        """

        if not user_id:
            raise ValueError("user_id cannot be empty")

        if not agent_id:
            raise ValueError("agent_id cannot be empty")

        connection = self._connect()

        try:
            rows = connection.execute(
                """
                SELECT
                    authorization_id,
                    user_id,
                    agent_id,
                    active,
                    revoked,
                    created_at,
                    expires_at
                FROM authorizations
                WHERE user_id = ?
                  AND agent_id = ?
                ORDER BY created_at DESC
                """,
                (user_id, agent_id),
            ).fetchall()

            return [
                self._row_to_model(row)
                for row in rows
            ]

        except Exception as exc:
            raise AuthorizationError(
                "Failed to find authorizations"
            ) from exc

        finally:
            connection.close()

    def revoke(
        self,
        authorization_id: str,
    ) -> AgentAuthorization:
        """
        Explicitly revoke an authorization.

        Revocation is persistent and cannot be interpreted as approval.
        """

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            cursor = connection.execute(
                """
                UPDATE authorizations
                SET revoked = 1,
                    active = 0
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            )

            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise AuthorizationError(
                    "Authorization not found"
                )

            connection.execute("COMMIT")

            authorization = self.get(authorization_id)

            if authorization is None:
                raise AuthorizationError(
                    "Authorization disappeared after revocation"
                )

            return authorization

        except AuthorizationError:
            raise

        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise AuthorizationError(
                "Failed to revoke authorization"
            ) from exc

        finally:
            connection.close()

    def deactivate(
        self,
        authorization_id: str,
    ) -> AgentAuthorization:
        """
        Deactivate an authorization without marking it as revoked.
        """

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            cursor = connection.execute(
                """
                UPDATE authorizations
                SET active = 0
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            )

            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise AuthorizationError(
                    "Authorization not found"
                )

            connection.execute("COMMIT")

            authorization = self.get(authorization_id)

            if authorization is None:
                raise AuthorizationError(
                    "Authorization disappeared after deactivation"
                )

            return authorization

        except AuthorizationError:
            raise

        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise AuthorizationError(
                "Failed to deactivate authorization"
            ) from exc

        finally:
            connection.close()

    def check(
        self,
        proposal: IntentProposal,
    ) -> AuthorizationDecision:
        """
        Resolve the server-owned authorization for the proposal and verify it.

        Any active, non-revoked, non-expired authorization matching the
        user/agent pair may authorize the request.
        """

        authorizations = self.find_for_agent(
            user_id=proposal.user_id,
            agent_id=proposal.agent_id,
        )

        if not authorizations:
            return AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_NOT_FOUND",
                authorization_id=None,
            )

        verifier = AuthorizationEngine()

        first_failure: AuthorizationDecision | None = None

        for authorization in authorizations:
            decision = verifier.verify(
                proposal,
                authorization,
            )

            if decision.allowed:
                return decision

            if first_failure is None:
                first_failure = decision

        return first_failure or AuthorizationDecision(
            allowed=False,
            reason="AUTHORIZATION_REJECTED",
            authorization_id=None,
        )

    @staticmethod
    def _row_to_model(
        row: sqlite3.Row,
    ) -> AgentAuthorization:
        created_at = datetime.fromisoformat(
            str(row["created_at"])
        )

        expires_at_value = row["expires_at"]

        expires_at = (
            datetime.fromisoformat(str(expires_at_value))
            if expires_at_value is not None
            else None
        )

        return AgentAuthorization(
            user_id=str(row["user_id"]),
            agent_id=str(row["agent_id"]),
            authorization_id=str(
                row["authorization_id"]
            ),
            active=bool(row["active"]),
            revoked=bool(row["revoked"]),
            created_at=created_at,
            expires_at=expires_at,
        )