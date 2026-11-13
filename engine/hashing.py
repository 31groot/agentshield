from __future__ import annotations

import hashlib
import json

from models.authorization import AgentAuthorization
from models.intent import IntentItem, IntentProposal


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
        return self.canonicalize_fields(
            authorization,
            user_id=proposal.user_id,
            agent_id=proposal.agent_id,
            merchant_id=proposal.merchant_id,
            amount_paise=proposal.amount_paise,
            currency=proposal.currency,
            items=proposal.items,
            action_type=proposal.action_type,
        )

    def canonicalize_fields(
        self,
        authorization: AgentAuthorization,
        *,
        user_id: str,
        agent_id: str,
        merchant_id: str,
        amount_paise: int,
        currency: str,
        items: list[IntentItem],
        action_type: str,
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
                "user_id": user_id,
                "agent_id": agent_id,
                "merchant_id": merchant_id,
                "amount_paise": amount_paise,
                "currency": currency,
                "items": sorted(
                    [
                        {
                            "sku": item.sku,
                            "quantity": item.quantity,
                        }
                        for item in items
                    ],
                    key=lambda item: item["sku"],
                ),
                "action_type": action_type,
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

    def hash_fields(
        self,
        authorization: AgentAuthorization,
        **fields: object,
    ) -> str:
        canonical = self.canonicalize_fields(
            authorization,
            **fields,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
