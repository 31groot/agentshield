from __future__ import annotations

from datetime import datetime, timezone

from models.intent import IntentProposal
from models.policy import AgentAuthorization, AuthorizationDecision


class AuthorizationEngine:
    """
    
        Determine whether the AI agent is authorized to act
        on behalf of the specified user.

    """

    def verify(
        self,
        proposal: IntentProposal,
        authorization: AgentAuthorization,
    ) -> AuthorizationDecision:
        """
        Verify the identity relationship between the
        proposal's user/agent and the stored authorization.
        """

        # 1. Authorization must be active.
        if not authorization.active:
            return AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_INACTIVE",
                authorization_id=authorization.authorization_id,
            )

        # 2. Authorization must not have been revoked.
        if authorization.revoked:
            return AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_REVOKED",
                authorization_id=authorization.authorization_id,
            )

        # 3. Check expiration.
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

        # 4. User in proposal must match authorized user.
        if proposal.user_id != authorization.user_id:
            return AuthorizationDecision(
                allowed=False,
                reason="USER_MISMATCH",
                authorization_id=authorization.authorization_id,
            )

        # 5. Agent in proposal must match authorized agent.
        if proposal.agent_id != authorization.agent_id:
            return AuthorizationDecision(
                allowed=False,
                reason="AGENT_MISMATCH",
                authorization_id=authorization.authorization_id,
            )

        # All authorization checks passed.
        return AuthorizationDecision(
            allowed=True,
            reason="AUTHORIZATION_APPROVED",
            authorization_id=authorization.authorization_id,
        )