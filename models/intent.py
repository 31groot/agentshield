from __future__ import annotations

from datetime import datetime, timezone

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
)
class AuthorizationInterpretation(BaseModel):
    """
    Claude's structured interpretation of what the user authorized.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    max_amount_paise: StrictInt | None = Field(
        default=None,
        gt=0,
        description="Maximum amount the user appears to authorize, in paise.",
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
        description="Currency expressed or implied by the user.",
    )

    product_constraints: list[StrictStr] = Field(
        default_factory=list,
        description="Products/categories the user appears to authorize.",
    )

    allowed_merchants: list[StrictStr] = Field(
        default_factory=list,
        description=(
            "Merchants explicitly permitted by the user. "
            "Empty means no merchant was explicitly specified."
        ),
    )

    max_quantity: StrictInt | None = Field(
        default=None,
        ge=1,
        description="Maximum quantity explicitly authorized by the user.",
    )

    constraints: list[StrictStr] = Field(
        default_factory=list,
        description="Human-readable constraints extracted from the request.",
    )
class IntentItem(BaseModel):
    """
    One concrete line item.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    sku: StrictStr = Field(
        min_length=1,
        description="Concrete product SKU.",
    )

    quantity: int = Field(
        ge=1,
        description="Number of units of this SKU.",
    )
class IntentProposal(BaseModel):
    """
    The AI may propose an action, but it cannot authorize or execute it.

    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    # Identity
    user_id: StrictStr = Field(
        min_length=1,
        description="User on whose behalf the action is proposed.",
    )

    agent_id: StrictStr = Field(
        min_length=1,
        description="AI agent producing the proposal.",
    )

    intent_id: StrictStr = Field(
        min_length=1,
        description="Unique identifier for this intent.",
    )

    # Original user evidence
    raw_user_prompt: StrictStr = Field(
        min_length=1,
        description="Original user request exactly as received.",
    )

    # Transaction details
    merchant_id: StrictStr = Field(
        min_length=1,
        description="Target merchant identifier.",
    )

    amount_paise: StrictInt = Field(
        gt=0.0,
        description="Concrete transaction amount proposed by the AI in paise.",
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
        description="Transaction currency.",
    )

    items: list[IntentItem] = Field(
    min_length=1,
    description="Concrete line items selected by the AI.",
    )

    action_type: StrictStr = Field(
        min_length=1,
        description="Type of financial action being proposed.",
    )

    # Replay / validity protection
    nonce: StrictStr = Field(
        min_length=1,
        description="Single-use value used for replay protection.",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Time at which the intent was created.",
    )

    ttl_seconds: int = Field(
        default=300,
        gt=0,
        le=600,
        description="Maximum validity period of the intent.",
    )


class AgentRequestAnalysis(BaseModel):
    """
    Complete analysis returned by the AI layer.

    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    raw_user_prompt: StrictStr = Field(
        min_length=1,
        description="Original user request.",
    )

    authorization: AuthorizationInterpretation = Field(
        description="Claude's interpretation of the user's constraints.",
    )

    intent_proposal: IntentProposal = Field(
        description="Concrete transaction proposed by Claude.",
    )