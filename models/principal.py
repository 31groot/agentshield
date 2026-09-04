from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class AuthenticatedPrincipal(BaseModel):
    """
    Server-derived API identity.

    The frontend never supplies user_id or agent_id as authoritative
    identity. These values are attached by the authenticated server
    principal.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    user_id: StrictStr = Field(min_length=1)
    agent_id: StrictStr = Field(min_length=1)
