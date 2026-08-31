from __future__ import annotations

from datetime import datetime

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class IdempotencyStatus(str, Enum):
    """
    Lifecycle of an idempotency record.

    These values describe the execution claim/result.
    They are not a replacement for the transaction state machine.
    """

    ACQUIRED = "ACQUIRED"
    COMPLETED = "COMPLETED"
    FAILED_SAFE_TO_RETRY = "FAILED_SAFE_TO_RETRY"


class IdempotencyRecord(BaseModel):
    """
    Persistent record representing ownership of an execution key.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    idempotency_key: StrictStr = Field(
        min_length=1,
        description="Unique key identifying one logical execution.",
    )

    transaction_id: StrictStr = Field(
        min_length=1,
        description="Transaction associated with the execution.",
    )

    status: IdempotencyStatus = Field(
        description="Current idempotency execution status.",
    )

    created_at: datetime = Field(
        description="UTC timestamp when the idempotency record was created.",
    )