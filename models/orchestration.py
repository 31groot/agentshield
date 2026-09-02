from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from models.mandate import Mandate
from models.transaction import TransactionRecord


class OrchestrationResult(BaseModel):
    """
    Result of one AgentShield execution orchestration.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    transaction: TransactionRecord = Field(
        description="Current server-owned transaction record.",
    )

    mandate: Mandate = Field(
        description="Signed mandate governing the transaction.",
    )

    status: StrictStr = Field(
        min_length=1,
        description="High-level orchestration status.",
    )