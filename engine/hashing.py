from __future__ import annotations

import hashlib
import json

from models.authorization import AgentAuthorization
from models.intent import IntentProposal


class IntentHasher:
    """
    SHA-256 fingerprint of the server-owned authorization
    and concrete transaction proposal.
    """

    def canonicalize(
        self,
        authorization: AgentAuthorization,
        proposal: IntentProposal,
    ) -> str:
        payload = {
            "authorization": {
                "authorization_id": authorization.authorization_id,
                "user_id": authorization.user_id,
                "agent_id": authorization.agent_id,
                "max_amount_paise": authorization.max_amount_paise,
                "allowed_merchants": sorted(
                    authorization.allowed_merchants
                ),
                "allowed_categories": sorted(
                    authorization.allowed_categories
                ),
                "allowed_skus": sorted(
                    authorization.allowed_skus
                ),
                "max_quantity": authorization.max_quantity,
                "currency": authorization.currency,
            },
            "transaction": {
                "user_id": proposal.user_id,
                "agent_id": proposal.agent_id,
                "merchant_id": proposal.merchant_id,
                "amount_paise": proposal.amount_paise,
                "currency": proposal.currency,
                "items": sorted(
                    [
                        {
                            "sku": item.sku,
                            "quantity": item.quantity,
                        }
                        for item in proposal.items
                    ],
                    key=lambda item: item["sku"],
                ),
                "action_type": proposal.action_type,
            },
        }

        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def hash(
        self,
        authorization: AgentAuthorization,
        proposal: IntentProposal,
    ) -> str:
        canonical = self.canonicalize(
            authorization,
            proposal,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()