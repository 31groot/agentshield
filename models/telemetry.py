from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class WebhookTelemetryEventType(str, Enum):
    """
    Observable lifecycle events for Razorpay webhooks.

    These events are telemetry only. They never grant or deny
    financial authorization.
    """

    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    WEBHOOK_SIGNATURE_VERIFIED = "WEBHOOK_SIGNATURE_VERIFIED"
    WEBHOOK_SIGNATURE_REJECTED = "WEBHOOK_SIGNATURE_REJECTED"
    WEBHOOK_REJECTED = "WEBHOOK_REJECTED"
    WEBHOOK_DUPLICATE = "WEBHOOK_DUPLICATE"
    WEBHOOK_CORRELATED = "WEBHOOK_CORRELATED"
    WEBHOOK_UNKNOWN_TRANSACTION = "WEBHOOK_UNKNOWN_TRANSACTION"
    PAYMENT_RECONCILED = "PAYMENT_RECONCILED"


class WebhookTelemetryEvent(BaseModel):
    """
    One immutable webhook telemetry record.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    telemetry_id: StrictStr = Field(
        min_length=1,
    )

    event_type: WebhookTelemetryEventType

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    webhook_event_id: StrictStr = Field(
        min_length=1,
    )

    transaction_id: StrictStr | None = Field(
        default=None,
    )

    payment_id: StrictStr | None = Field(
        default=None,
    )

    order_id: StrictStr | None = Field(
        default=None,
    )

    details: dict[str, Any] = Field(
        default_factory=dict,
    )
