from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from models.transaction import TransactionState


class WebhookResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    status: StrictStr = Field(min_length=1)
    event_id: StrictStr = Field(min_length=1)
    transaction_id: StrictStr = Field(min_length=1)
    transaction_state: TransactionState
