from __future__ import annotations

from engine.catalog import SQLiteCatalog
from models.policy import PolicyDecision, TransactionPolicy
from models.authorization import AgentAuthorization
from models.intent import IntentProposal


class DeterministicPolicyEngine:
    """
    Decide whether a specific IntentProposal satisfies the
    AgentShield policy and the interpreted user constraints.

    When a server-owned catalog is supplied, factual product data
    from that catalog is treated as authoritative.
    """

    def evaluate(
        self,
        proposal: IntentProposal,
        authorization: AgentAuthorization,
        policy: TransactionPolicy,
        *,
        catalog: SQLiteCatalog | None = None,
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

        # 2. Hard INR boundary

        if proposal.currency != "INR":
            return self._block(
                "CURRENCY_NOT_ALLOWED",
                expected="INR",
                received=proposal.currency,
            )

        if policy.currency != "INR":
            return self._block(
                "POLICY_CURRENCY_NOT_ALLOWED",
                expected="INR",
                received=policy.currency,
            )

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

        # 3. Catalog facts

        catalog_total_paise = 0

        if catalog is not None:
            for item in proposal.items:
                product = catalog.get(item.sku)

                if product is None:
                    return self._block(
                        "SKU_NOT_FOUND_IN_CATALOG",
                        sku=item.sku,
                    )

                if product.currency != "INR":
                    return self._block(
                        "CATALOG_CURRENCY_NOT_ALLOWED",
                        sku=item.sku,
                        currency=product.currency,
                    )

                if product.merchant_id != proposal.merchant_id:
                    return self._block(
                        "CATALOG_MERCHANT_MISMATCH",
                        sku=item.sku,
                        expected=proposal.merchant_id,
                        received=product.merchant_id,
                    )

                if product.stock < item.quantity:
                    return self._block(
                        "INSUFFICIENT_STOCK",
                        sku=item.sku,
                        available=str(product.stock),
                        requested=str(item.quantity),
                    )

                if (
                    policy.allowed_categories
                    and product.category
                    not in policy.allowed_categories
                ):
                    return self._block(
                        "CATEGORY_NOT_ALLOWED",
                        sku=item.sku,
                        category=product.category,
                    )

                catalog_total_paise += (
                    product.price_paise * item.quantity
                )

            if catalog_total_paise != proposal.amount_paise:
                return self._block(
                    "AMOUNT_DOES_NOT_MATCH_CATALOG",
                    expected=str(catalog_total_paise),
                    received=str(proposal.amount_paise),
                )

        # 4. Transaction amount

        amount = proposal.amount_paise

        if amount < policy.min_amount_paise:
            return self._block(
                "AMOUNT_BELOW_ECONOMIC_FLOOR",
                minimum=str(policy.min_amount_paise),
                received=str(amount),
            )

        if amount > policy.max_amount_paise:
            return self._block(
                "AMOUNT_EXCEEDS_POLICY_LIMIT",
                maximum=str(policy.max_amount_paise),
                received=str(amount),
            )
        
        if amount > authorization.max_amount_paise:
            
            return self._block(
                "AMOUNT_EXCEEDS_USER_AUTHORIZATION",
                maximum=str(authorization.max_amount_paise),
                received=str(amount),
            )

        # 5. Merchant

        if (
            policy.allowed_merchants
            and proposal.merchant_id
            not in policy.allowed_merchants
        ):
            return self._block(
                "MERCHANT_NOT_ALLOWED",
                merchant_id=proposal.merchant_id,
            )

        if (
            authorization.allowed_merchants
            and proposal.merchant_id
            not in authorization.allowed_merchants
        ):
            return self._block(
                "MERCHANT_NOT_AUTHORIZED_BY_USER",
                merchant_id=proposal.merchant_id,
            )

        # 6. Quantity

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

        if total_quantity > authorization.max_quantity:

            return self._block(
                "QUANTITY_EXCEEDS_USER_AUTHORIZATION",
                maximum=str(authorization.max_quantity),
                received=str(total_quantity),
            )

        # 7. SKU restrictions

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

        # 8. Bank rail health

        if not policy.bank_rail_available:
            return self._block(
                "BANK_RAIL_UNAVAILABLE",
            )

        # Everything passed.

        return PolicyDecision(
            allowed=True,
            reason="POLICY_APPROVED",
            details={
                "amount_paise": str(amount),
                "merchant_id": proposal.merchant_id,
                "quantity": str(total_quantity),
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