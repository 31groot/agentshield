from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from models.transaction import TransactionRecord


class RecoveryResult(BaseModel):
    """
    Result produced by the transaction recovery engine.

    This is a data contract only. It does not perform
    any recovery operation itself.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    transaction: TransactionRecord = Field(
        description="Transaction after the requested recovery transition.",
    )

    action: StrictStr = Field(
        min_length=1,
        description="Recovery action requested by the engine.",
    )