from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class AgentAuthorization(BaseModel):
    """
    Trusted authorization record representing whether an AI agent
    is allowed to act on behalf of a specific user.

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

    active: bool = Field(
        default=True,
        description="Whether this authorization is currently active.",
    )

    revoked: bool = Field(
        default=False,
        description="Whether the user has explicitly revoked the authorization.",
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

    allowed: bool = Field(
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

    