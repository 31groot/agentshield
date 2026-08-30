from __future__ import annotations

from models.intent import AuthorizationInterpretation, IntentProposal
from models.policy import PolicyDecision, TransactionPolicy


class DeterministicPolicyEngine:
    """
        Decide whether a specific IntentProposal satisfies the
        AgentShield policy and the interpreted user constraints.

    """

    def evaluate(
        self,
        proposal: IntentProposal,
        authorization: AuthorizationInterpretation,
        policy: TransactionPolicy,
    ) -> PolicyDecision:

        # 1. Identity

        if proposal.user_id != policy.user_id:
            return self._block(
                "USER_POLICY_MISMATCH",
                expected=policy.user_id,
                received=proposal.user_id,
            )

        if proposal.agent_id != policy.agent_id:
            return self._block(
                "AGENT_POLICY_MISMATCH",
                expected=policy.agent_id,
                received=proposal.agent_id,
            )

        
        # 2. Currency

        if proposal.currency != policy.currency:
            return self._block(
                "CURRENCY_NOT_ALLOWED",
                expected=policy.currency,
                received=proposal.currency,
            )

        if authorization.currency != proposal.currency:
            return self._block(
                "AUTHORIZATION_CURRENCY_MISMATCH",
                authorization=authorization.currency,
                proposal=proposal.currency,
            )

        # 3. Transaction amount

        amount = proposal.requested_amount_inr

        if amount < policy.min_amount_inr:
            return self._block(
                "AMOUNT_BELOW_ECONOMIC_FLOOR",
                minimum=f"{policy.min_amount_inr:.2f}",
                received=f"{amount:.2f}",
            )

        if amount > policy.max_amount_inr:
            return self._block(
                "AMOUNT_EXCEEDS_POLICY_LIMIT",
                maximum=f"{policy.max_amount_inr:.2f}",
                received=f"{amount:.2f}",
            )

        # User authorization may impose an even tighter limit.
        if (
            authorization.max_amount_inr is not None
            and amount > authorization.max_amount_inr
        ):
            return self._block(
                "AMOUNT_EXCEEDS_USER_AUTHORIZATION",
                maximum=f"{authorization.max_amount_inr:.2f}",
                received=f"{amount:.2f}",
            )

        # 4. Merchant

        if (
            policy.allowed_merchants
            and proposal.merchant_id not in policy.allowed_merchants
        ):
            return self._block(
                "MERCHANT_NOT_ALLOWED",
                merchant_id=proposal.merchant_id,
            )

        # If the user's authorization explicitly names merchants,
        # the proposal must respect them.
        if (
            authorization.allowed_merchants
            and proposal.merchant_id not in authorization.allowed_merchants
        ):
            return self._block(
                "MERCHANT_NOT_AUTHORIZED_BY_USER",
                merchant_id=proposal.merchant_id,
            )

        # 5. Quantity

        total_quantity = sum(
            item.quantity
            for item in proposal.items
        )

        if total_quantity > policy.max_quantity:
            return self._block(
                "QUANTITY_EXCEEDS_POLICY_LIMIT",
                maximum=str(policy.max_quantity),
                received=str(total_quantity),
            )

        if (
            authorization.max_quantity is not None
            and total_quantity > authorization.max_quantity
        ):
            return self._block(
                "QUANTITY_EXCEEDS_USER_AUTHORIZATION",
                maximum=str(authorization.max_quantity),
                received=str(total_quantity),
            )



        # 6. SKU restrictions

        if (
            policy.allowed_skus
            and any(
                item.sku not in policy.allowed_skus
                for item in proposal.items
            )
        ):
            return self._block(
                "SKU_NOT_ALLOWED",
                skus=",".join(
                    item.sku for item in proposal.items
                ),
            )

        # 7. Product constraint check
        

        # 8. Bank rail health

        if not policy.bank_rail_available:
            return self._block(
                "BANK_RAIL_UNAVAILABLE",
            )

        
        # Everything passed

        return PolicyDecision(
            allowed=True,
            reason="POLICY_APPROVED",
            details={
                "amount": f"{amount:.2f}",
                "merchant_id": proposal.merchant_id,
                "quantity": str(
                    sum(item.quantity for item in proposal.items)
                ),
            },
        )

    @staticmethod
    def _block(
        reason: str,
        **details: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            allowed=False,
            reason=reason,
            details=details,
        )