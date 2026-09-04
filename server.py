from __future__ import annotations

import os

from api.main import create_app
from application.container import ApplicationContainer
from models.intent import AgentRequestAnalysis
from models.policy import TransactionPolicy


def demo_policy_provider(
    analysis: AgentRequestAnalysis,
) -> TransactionPolicy:
    """
    Explicit demo policy.

    This is intentionally separate from the default fail-closed
    policy provider so demo configuration cannot silently become
    the application's default behavior.
    """
    return TransactionPolicy(
        user_id=analysis.intent_proposal.user_id,
        agent_id=analysis.intent_proposal.agent_id,
        max_amount_paise=500000,
        min_amount_paise=10000,
        allowed_merchants=[],
        allowed_categories=[],
        allowed_skus=[],
        max_quantity=10,
        currency="INR",
        bank_rail_available=True,
    )


demo_mode = (
    os.getenv(
        "AGENTSHIELD_DEMO_MODE",
        "false",
    )
    .strip()
    .lower()
    == "true"
)

container = ApplicationContainer.from_environment(
    policy_provider=(
        demo_policy_provider
        if demo_mode
        else None
    )
)

app = create_app(
    container=container,
)

__all__ = ["app"]