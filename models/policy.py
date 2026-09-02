from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
)
class TransactionPolicy(BaseModel):
    """
    Deterministic rules applied to a concrete transaction.

    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    user_id: StrictStr = Field(
        min_length=1,
        description="User this policy belongs to.",
    )

    agent_id: StrictStr = Field(
        min_length=1,
        description="Agent this policy applies to.",
    )

    max_amount_paise: StrictInt = Field(
        gt=0.0,
        description="Maximum amount allowed for one transaction in paise.",
    )

    min_amount_paise: StrictInt = Field(
        default=100,
        gt=0.0,
        description="Minimum economically meaningful transaction amount in.",
    )

    allowed_merchants: list[StrictStr] = Field(
        default_factory=list,
        description=(
            "Explicitly allowed merchants. "
            "Empty means no merchant-specific restriction."
        ),
    )

    allowed_categories: list[StrictStr] = Field(
        default_factory=list,
        description=(
            "Explicitly allowed product categories. "
            "Empty means no category-specific restriction."
        ),
    )

    allowed_skus: list[StrictStr] = Field(
        default_factory=list,
        description=(
            "Explicitly allowed SKUs. "
            "Empty means no SKU-specific restriction."
        ),
    )

    max_quantity: StrictInt = Field(
        default=10,
        ge=1,
        description="Maximum quantity allowed in one transaction.",
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
        description="Currency enforced by the policy.",
    )

    bank_rail_available: StrictBool = Field(
        default=True,
        description="Whether the relevant payment rail is currently available.",
    )


class PolicyDecision(BaseModel):
    """
    Deterministic result produced by the policy engine.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    allowed: StrictBool

    reason: StrictStr = Field(
        min_length=1,
        description="Machine-readable reason for the decision.",
    )

    details: dict[str, str] = Field(
        default_factory=dict,
        description="Additional deterministic decision details.",
    )