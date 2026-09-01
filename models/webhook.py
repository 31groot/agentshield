from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
)


class WebhookEventType(str, Enum):
    """
    Razorpay webhook events understood by AgentShield.

    """

    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_FAILED = "payment.failed"


class WebhookEvent(BaseModel):
    """
    Normalized Razorpay webhook event.

    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    event_id: StrictStr = Field(
        min_length=1,
        description="Razorpay webhook event identifier.",
    )

    event_type: WebhookEventType

    payment_id: StrictStr = Field(
        min_length=1,
        description="Razorpay payment identifier.",
    )

    order_id: StrictStr | None = Field(
        default=None,
        description="Associated Razorpay order identifier.",
    )

    amount_paise: StrictInt = Field(
        gt=0,
        description="Payment amount reported by Razorpay in paise.",
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
        description="Payment currency reported by Razorpay.",
    )

    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time when AgentShield received the event.",
    )

class WebhookProcessingStatus(str, Enum):
    """
    Lifecycle of a webhook event inside AgentShield.
    """

    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"

class WebhookEventRecord(BaseModel):
    """
    Persistent record of webhook processing.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    event_id: StrictStr = Field(
        min_length=1,
        description="Unique webhook event identifier.",
    )

    status: WebhookProcessingStatus = Field(
        description="Current webhook processing status.",
    )

    received_at: datetime = Field(
        description="UTC timestamp when the event was first received.",
    )

    processed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the event was successfully processed.",
    )