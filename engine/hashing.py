from __future__ import annotations

import hashlib
import json

from models.intent import AuthorizationInterpretation, IntentProposal


class IntentHasher:
    """
    SHA-256 fingerprint of the governed
    authorization + concrete transaction.
    """

    def canonicalize(
        self,
        authorization: AuthorizationInterpretation,
        proposal: IntentProposal,
    ) -> str:
        payload = {
            "authorization": {
                "max_amount_paise": authorization.max_amount_paise,
                "currency": authorization.currency,
                "product_constraints": sorted(
                    authorization.product_constraints
                ),
                "allowed_merchants": sorted(
                    authorization.allowed_merchants
                ),
                "max_quantity": authorization.max_quantity,
            },
            "transaction": {
                "user_id": proposal.user_id,
                "agent_id": proposal.agent_id,
                "merchant_id": proposal.merchant_id,
                "amount_inr": round(
                    proposal.amount_paise,
                    2,
                ),
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
        authorization: AuthorizationInterpretation,
        proposal: IntentProposal,
    ) -> str:
        canonical = self.canonicalize(
            authorization,
            proposal,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()