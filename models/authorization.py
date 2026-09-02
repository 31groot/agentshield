from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class AgentAuthorization(BaseModel):
    """
    Trusted, server-owned authorization record representing the bounded
    authority delegated by a user to a specific AI agent.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    user_id: StrictStr = Field(
        min_length=1,
        description="User who owns the financial authority.",
    )

    agent_id: StrictStr = Field(
        min_length=1,
        description="AI agent delegated authority by the user.",
    )

    authorization_id: StrictStr = Field(
        min_length=1,
        description="Unique identifier for this delegation.",
    )

    active: StrictBool = Field(
        default=True,
        description="Whether this authorization is currently active.",
    )

    revoked: StrictBool = Field(
        default=False,
        description="Whether the user has explicitly revoked the authorization.",
    )

    max_amount_paise: StrictInt = Field(
        gt=0,
        description="Maximum transaction amount authorized in paise.",
    )

    allowed_merchants: list[StrictStr] = Field(
        default_factory=list,
        description="Merchants this authorization permits.",
    )

    allowed_categories: list[StrictStr] = Field(
        default_factory=list,
        description="Product categories this authorization permits.",
    )

    allowed_skus: list[StrictStr] = Field(
        default_factory=list,
        description="Product SKUs this authorization permits.",
    )

    max_quantity: StrictInt = Field(
        default=1,
        ge=1,
        description="Maximum total quantity authorized for one execution.",
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
        description="Currency authorized for transactions.",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Time at which the authorization was created.",
    )

    expires_at: datetime | None = Field(
        default=None,
        description="Time after which the authorization is no longer valid.",
    )


class AuthorizationDecision(BaseModel):
    """
    Deterministic result produced by the authorization engine.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    allowed: StrictBool = Field(
        description="Whether the agent is authorized to act for the user.",
    )

    reason: StrictStr = Field(
        min_length=1,
        description="Machine-readable reason for the decision.",
    )

    authorization_id: StrictStr | None = Field(
        default=None,
        description="Authorization responsible for the decision.",
    )