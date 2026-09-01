from __future__ import annotations

import hashlib
import hmac
import json

from models.webhook import WebhookEvent, WebhookEventType


class RazorpayWebhookHandler:
    """
    Razorpay webhook verification and normalization layer.

    Responsibilities:
    - verify webhook authenticity
    - normalize supported payment events
    - provide deterministic reconciliation evidence

    """

    def __init__(self, webhook_secret: str) -> None:
        if not webhook_secret.strip():
            raise ValueError("webhook_secret cannot be empty")

        self._webhook_secret = webhook_secret.encode("utf-8")

    def verify_signature(
        self,
        *,
        raw_body: bytes,
        signature: str,
    ) -> bool:
        """
        Verify the Razorpay webhook signature.

        The raw request body MUST be used exactly as received.
        """

        if not signature.strip():
            return False

        expected = hmac.new(
            self._webhook_secret,
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(
            expected,
            signature,
        )

    def parse_event(
        self,
        *,
        raw_body: bytes,
        event_id: str,
    ) -> WebhookEvent:
        """
        Parse a verified Razorpay webhook body into an
        AgentShield WebhookEvent.
        """

        if not event_id.strip():
            raise ValueError("event_id cannot be empty")

        try:
            payload = json.loads(
                raw_body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "Invalid webhook JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                "Webhook payload must be a JSON object"
            )

        event_name = payload.get("event")

        if event_name == WebhookEventType.PAYMENT_CAPTURED.value:
            event_type = WebhookEventType.PAYMENT_CAPTURED

        elif event_name == WebhookEventType.PAYMENT_FAILED.value:
            event_type = WebhookEventType.PAYMENT_FAILED

        else:
            raise ValueError(
                f"Unsupported webhook event: {event_name}"
            )

        payment_container = payload.get(
            "payload",
            {},
        )

        if not isinstance(payment_container, dict):
            raise ValueError(
                "Invalid webhook payload"
            )

        payment_container = payment_container.get(
            "payment",
            {},
        )

        if not isinstance(payment_container, dict):
            raise ValueError(
                "Invalid payment payload"
            )

        payment = payment_container.get(
            "entity",
            {},
        )

        if not isinstance(payment, dict):
            raise ValueError(
                "Invalid payment entity"
            )

        payment_id = payment.get("id")

        if (
            not isinstance(payment_id, str)
            or not payment_id.strip()
        ):
            raise ValueError(
                "Webhook missing payment id"
            )

        order_id = payment.get("order_id")

        if order_id is not None:
            if not isinstance(order_id, str):
                raise ValueError(
                    "Invalid order id"
                )

            if not order_id.strip():
                raise ValueError(
                    "Invalid order id"
                )

        amount = payment.get("amount")

        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
        ):
            raise ValueError(
                "Webhook amount must be an integer"
            )

        if amount <= 0:
            raise ValueError(
                "Webhook amount must be positive"
            )

        currency = payment.get(
            "currency",
            "INR",
        )

        if not isinstance(currency, str):
            raise ValueError(
                "Webhook currency must be a string"
            )

        if not currency.strip():
            raise ValueError(
                "Webhook currency cannot be empty"
            )

        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payment_id=payment_id,
            order_id=order_id,
            amount_paise=amount,
            currency=currency,
        )