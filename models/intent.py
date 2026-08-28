from __future__ import annotations

from datetime import datetime, timezone

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictStr,
    field_validator,
)


class IntentProposal(BaseModel):
    

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

    # Transaction details
    merchant_id: StrictStr = Field(
        min_length=1,
        description="Target merchant identifier.",
    )

    requested_amount_inr: StrictFloat = Field(
        gt=0.0,
        description="Requested transaction amount in INR.",
    )

    currency: StrictStr = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="Transaction currency.",
    )

    sku_list: list[StrictStr] = Field(
        min_length=1,
        description="Concrete product SKUs selected by the agent.",
    )

    quantity: int = Field(
        default=1,
        ge=1,
        description="Number of units requested.",
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

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value != "INR":
            raise ValueError("Only INR is supported")
        return value

    @field_validator("sku_list")
    @classmethod
    def validate_sku_list(cls, value: list[str]) -> list[str]:
        cleaned = [sku.strip() for sku in value]

        if any(not sku for sku in cleaned):
            raise ValueError("SKU values cannot be empty")

        return cleaned