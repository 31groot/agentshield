from __future__ import annotations

from datetime import datetime, timezone

from engine.telemetry import WebhookTelemetryStore
from models.telemetry import (
    WebhookTelemetryEvent,
    WebhookTelemetryEventType,
)


def make_event(
    *,
    event_type: WebhookTelemetryEventType,
    event_id: str = "evt_001",
) -> WebhookTelemetryEvent:
    return WebhookTelemetryEvent(
        telemetry_id=f"telemetry_{event_id}",
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc),
        webhook_event_id=event_id,
        transaction_id="txn_001",
        payment_id="pay_001",
        order_id="order_001",
        details={
            "test": True,
        },
    )


def test_telemetry_event_round_trips(tmp_path):
    store = WebhookTelemetryStore(
        str(tmp_path / "telemetry.db")
    )

    event = make_event(
        event_type=(
            WebhookTelemetryEventType
            .WEBHOOK_RECEIVED
        )
    )

    store.append(event)

    events = store.list_events(
        webhook_event_id="evt_001",
    )

    assert events == [event]


def test_telemetry_can_filter_by_transaction(tmp_path):
    store = WebhookTelemetryStore(
        str(tmp_path / "telemetry.db")
    )

    store.append(
        make_event(
            event_type=(
                WebhookTelemetryEventType
                .WEBHOOK_RECEIVED
            )
        )
    )

    events = store.list_events(
        transaction_id="txn_001",
    )

    assert len(events) == 1


def test_telemetry_count_by_type(tmp_path):
    store = WebhookTelemetryStore(
        str(tmp_path / "telemetry.db")
    )

    store.append(
        make_event(
            event_type=(
                WebhookTelemetryEventType
                .WEBHOOK_RECEIVED
            )
        )
    )

    store.append(
        make_event(
            event_type=(
                WebhookTelemetryEventType
                .WEBHOOK_SIGNATURE_VERIFIED
            ),
            event_id="evt_002",
        )
    )

    assert store.count(
        WebhookTelemetryEventType.WEBHOOK_RECEIVED
    ) == 1

    assert store.count(
        WebhookTelemetryEventType.WEBHOOK_SIGNATURE_VERIFIED
    ) == 1

    assert store.count() == 2
