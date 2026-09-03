import hashlib
import hmac
import json

import pytest

from models.webhook import WebhookEventType
from webhooks.razorpay import RazorpayWebhookHandler


WEBHOOK_SECRET = "test-webhook-secret"


def make_payload(
    *,
    event: str = "payment.captured",
    event_id: str = "evt_001",
    payment_id: str = "pay_001",
    order_id: str = "order_001",
    amount: int = 450000,
) -> bytes:
    payload = {
        "id": event_id,
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                }
            }
        },
    }

    return json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")


def sign(body: bytes) -> str:
    return hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()


@pytest.fixture
def handler() -> RazorpayWebhookHandler:
    return RazorpayWebhookHandler(
        WEBHOOK_SECRET
    )


def test_valid_signature_is_accepted(handler):
    body = make_payload()

    signature = sign(body)

    assert handler.verify_signature(
        raw_body=body,
        signature=signature,
    ) is True


def test_invalid_signature_is_rejected(handler):
    body = make_payload()

    assert handler.verify_signature(
        raw_body=body,
        signature="invalid-signature",
    ) is False


def test_changed_body_invalidates_signature(handler):
    body = make_payload()

    signature = sign(body)

    mutated_body = make_payload(
        amount=999999,
    )

    assert handler.verify_signature(
        raw_body=mutated_body,
        signature=signature,
    ) is False


def test_payment_captured_is_parsed(handler):
    body = make_payload(
        event="payment.captured",
    )

    event = handler.parse_event(
        raw_body=body,
        event_id="evt_001",

    )

    assert event.event_id == "evt_001"
    assert event.event_type == (
        WebhookEventType.PAYMENT_CAPTURED
    )
    assert event.payment_id == "pay_001"
    assert event.order_id == "order_001"
    assert event.amount_paise == 450000


def test_payment_failed_is_parsed(handler):
    body = make_payload(
        event="payment.failed",
    )

    event = handler.parse_event(
        raw_body=body,
        event_id="evt_001",
    )

    assert event.event_type == (
        WebhookEventType.PAYMENT_FAILED
    )


def test_unsupported_event_is_rejected(handler):
    body = make_payload(
        event="unknown.event",
    )

    with pytest.raises(ValueError):
        handler.parse_event(
            raw_body=body,
            event_id="evt_001",
        )


def test_invalid_json_is_rejected(handler):
    body = b"not-json"

    with pytest.raises(ValueError):
        handler.parse_event(
            raw_body=body,
            event_id="evt_001",
        )


def test_missing_payment_id_is_rejected(handler):
    payload = {
        "id": "evt_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "order_id": "order_001",
                    "amount": 450000,
                }
            }
        },
    }

    body = json.dumps(payload).encode()

    with pytest.raises(ValueError):
        handler.parse_event(
            raw_body=body,
            event_id="evt_001",
        )


def test_float_amount_is_rejected(handler):
    payload = {
        "id": "evt_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_001",
                    "order_id": "order_001",
                    "amount": 450000.0,
                }
            }
        },
    }

    body = json.dumps(payload).encode()

    with pytest.raises(ValueError):
        handler.parse_event(
            raw_body=body,
            event_id="evt_001",
        )
def test_verify_and_parse_event_requires_valid_signature(
    handler,
):
    body = make_payload()

    signature = sign(body)

    event = handler.verify_and_parse_event(
        raw_body=body,
        signature=signature,
        event_id="evt_001",
    )

    assert event.event_id == "evt_001"
    assert event.event_type == (
        WebhookEventType.PAYMENT_CAPTURED
    )
    assert event.payment_id == "pay_001"


def test_verify_and_parse_event_rejects_invalid_signature(
    handler,
):
    body = make_payload()

    with pytest.raises(
        ValueError,
        match="Invalid webhook signature",
    ):
        handler.verify_and_parse_event(
            raw_body=body,
            signature="invalid-signature",
            event_id="evt_001",
        )