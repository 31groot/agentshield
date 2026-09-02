from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from engine.hashing import IntentHasher
from models.authorization import AgentAuthorization
from models.intent import IntentProposal
from models.mandate import Mandate


class AP2AlignedMandateEngine:
    """
    AP2-aligned MVP mandate engine.

    Responsibilities:
    - create cryptographically signed mandates
    - verify mandate authenticity
    - verify mandate freshness
    - verify that the proposal still matches the signed intent

    The mandate is bound to the server-owned authorization record
    and the concrete transaction proposal.
    """

    def __init__(
        self,
        secret_key: bytes,
        *,
        hasher: IntentHasher | None = None,
    ) -> None:
        if not secret_key:
            raise ValueError("secret_key cannot be empty")

        self._secret_key = secret_key
        self._hasher = hasher or IntentHasher()

    def create(
        self,
        *,
        authorization: AgentAuthorization,
        proposal: IntentProposal,
        issued_at: datetime | None = None,
    ) -> Mandate:
        """
        Create a signed mandate for an already-governed proposal.

        """

        if issued_at is None:
            issued_at = datetime.now(timezone.utc)

        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(
                tzinfo=timezone.utc
            )

        intent_hash = self._hasher.hash(
            authorization,
            proposal,
        )

        issued_at, expires_at = Mandate.create_times(
            issued_at=issued_at,
            ttl_seconds=proposal.ttl_seconds,
        )

        payload = self._signature_payload(
            user_id=proposal.user_id,
            agent_id=proposal.agent_id,
            merchant_id=proposal.merchant_id,
            amount_paise=proposal.amount_paise,
            intent_hash=intent_hash,
            nonce=proposal.nonce,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        signature = self._sign(payload)

        return Mandate(
            user_id=proposal.user_id,
            agent_id=proposal.agent_id,
            merchant_id=proposal.merchant_id,
            amount_paise=proposal.amount_paise,
            intent_hash=intent_hash,
            nonce=proposal.nonce,
            issued_at=issued_at,
            expires_at=expires_at,
            signature=signature,
        )

    def verify(
        self,
        *,
        mandate: Mandate,
        authorization: AgentAuthorization,
        proposal: IntentProposal,
        now: datetime | None = None,
    ) -> bool:
        """
        Verify that:

        1. The mandate hasn't expired.
        2. The proposal still matches the signed mandate.
        3. The intent hash still matches.
        4. The HMAC signature is authentic.
        """

        if now is None:
            now = datetime.now(timezone.utc)

        if now.tzinfo is None:
            now = now.replace(
                tzinfo=timezone.utc
            )

        # 1. Identity binding
        if proposal.user_id != mandate.user_id:
            return False

        if proposal.agent_id != mandate.agent_id:
            return False

        if proposal.merchant_id != mandate.merchant_id:
            return False

        # 2. Amount binding
        if proposal.amount_paise != mandate.amount_paise:
            return False

        # 3. Nonce binding
        if proposal.nonce != mandate.nonce:
            return False

        # 4. Time validity
        if now < mandate.issued_at:
            return False

        if now >= mandate.expires_at:
            return False

        # 5. Recompute intent hash
        current_intent_hash = self._hasher.hash(
            authorization,
            proposal,
        )

        if not hmac.compare_digest(
            current_intent_hash,
            mandate.intent_hash,
        ):
            return False

        # 6. Verify HMAC signature
        payload = self._signature_payload(
            user_id=mandate.user_id,
            agent_id=mandate.agent_id,
            merchant_id=mandate.merchant_id,
            amount_paise=mandate.amount_paise,
            intent_hash=mandate.intent_hash,
            nonce=mandate.nonce,
            issued_at=mandate.issued_at,
            expires_at=mandate.expires_at,
        )

        expected_signature = self._sign(payload)

        return hmac.compare_digest(
            expected_signature,
            mandate.signature,
        )

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self._secret_key,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _signature_payload(
        *,
        user_id: str,
        agent_id: str,
        merchant_id: str,
        amount_paise: int,
        intent_hash: str,
        nonce: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> str:
        return "|".join(
            [
                user_id,
                agent_id,
                merchant_id,
                str(amount_paise),
                intent_hash,
                nonce,
                issued_at.isoformat(),
                expires_at.isoformat(),
            ]
        )