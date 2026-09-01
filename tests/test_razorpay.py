from __future__ import annotations

import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from integrations.razorpay import (
    RazorpayAuthenticationError,
    RazorpayBadRequestError,
    RazorpayClient,
    RazorpayConflictError,
    RazorpayError,
    RazorpayNetworkError,
    RazorpayRateLimitError,
    RazorpayResponseError,
)
from models.razorpay import (
    RazorpayOrderResult,
    RazorpayPaymentResult,
    RazorpayRefundResult,
)


def make_client(
    handler,
) -> tuple[RazorpayClient, httpx.AsyncClient]:
    """
    Create a Razorpay client backed by httpx.MockTransport.

    No real Razorpay API calls are made.
    """

    transport = httpx.MockTransport(handler)

    async_client = httpx.AsyncClient(
        transport=transport,
    )

    client = RazorpayClient(
        key_id="rzp_test_key",
        key_secret="test_secret",
        client=async_client,
    )

    return client, async_client


# Order


@pytest.mark.asyncio
async def test_create_order():
    async def handler(request: httpx.Request):
        assert request.method == "POST"

        assert str(request.url) == ("https://api.razorpay.com/v1/orders")

        assert request.headers["content-type"] == ("application/json")

        payload = json.loads(request.content.decode("utf-8"))

        assert payload == {
            "amount": 450000,
            "currency": "INR",
            "receipt": "txn_001",
        }

        authorization = request.headers.get("authorization")

        assert authorization is not None

        expected_credentials = base64.b64encode(b"rzp_test_key:test_secret").decode(
            "ascii"
        )

        assert authorization == (f"Basic {expected_credentials}")

        return httpx.Response(
            200,
            json={
                "id": "order_001",
                "amount": 450000,
                "currency": "INR",
                "status": "created",
            },
        )

    client, async_client = make_client(handler)

    try:
        result = await client.create_order(
            amount_paise=450000,
            currency="INR",
            receipt="txn_001",
        )

        assert isinstance(
            result,
            RazorpayOrderResult,
        )

        assert result.order_id == "order_001"
        assert result.amount_paise == 450000
        assert result.currency == "INR"
        assert result.status == "created"

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_create_order_with_notes():
    async def handler(request: httpx.Request):
        payload = json.loads(request.content.decode("utf-8"))

        assert payload == {
            "amount": 450000,
            "currency": "INR",
            "receipt": "txn_001",
            "notes": {
                "transaction_id": "txn_001",
                "source": "agentshield",
            },
        }

        return httpx.Response(
            200,
            json={
                "id": "order_001",
                "amount": 450000,
                "currency": "INR",
                "status": "created",
            },
        )

    client, async_client = make_client(handler)

    try:
        result = await client.create_order(
            amount_paise=450000,
            receipt="txn_001",
            notes={
                "transaction_id": "txn_001",
                "source": "agentshield",
            },
        )

        assert isinstance(
            result,
            RazorpayOrderResult,
        )

        assert result.order_id == "order_001"

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount",
    [
        0,
        -1,
    ],
)
async def test_create_order_rejects_non_positive_amount(
    amount: int,
):
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="amount_paise must be positive",
        ):
            await client.create_order(
                amount_paise=amount,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_create_order_rejects_empty_receipt():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="receipt cannot be empty",
        ):
            await client.create_order(
                amount_paise=450000,
                receipt="   ",
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_create_order_rejects_long_receipt():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="40 characters",
        ):
            await client.create_order(
                amount_paise=450000,
                receipt="x" * 41,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_create_order_rejects_too_many_notes():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        notes = {f"key_{i}": "value" for i in range(16)}

        with pytest.raises(
            ValueError,
            match="15 entries",
        ):
            await client.create_order(
                amount_paise=450000,
                notes=notes,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_create_order_rejects_malformed_response():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "amount": 450000,
                "currency": "INR",
                "status": "created",
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayResponseError,
            match="missing id",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


# Payment


@pytest.mark.asyncio
async def test_fetch_payment():
    async def handler(request: httpx.Request):
        assert request.method == "GET"

        assert str(request.url) == ("https://api.razorpay.com/v1/payments/pay_001")

        return httpx.Response(
            200,
            json={
                "id": "pay_001",
                "amount": 450000,
                "currency": "INR",
                "status": "captured",
                "order_id": "order_001",
            },
        )

    client, async_client = make_client(handler)

    try:
        result = await client.fetch_payment("pay_001")

        assert isinstance(
            result,
            RazorpayPaymentResult,
        )

        assert result.payment_id == "pay_001"
        assert result.order_id == "order_001"
        assert result.amount_paise == 450000
        assert result.currency == "INR"
        assert result.status == "captured"

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_fetch_payment_rejects_empty_payment_id():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="payment_id cannot be empty",
        ):
            await client.fetch_payment("   ")

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_fetch_payment_rejects_malformed_response():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "amount": 450000,
                "currency": "INR",
                "status": "captured",
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayResponseError,
            match="missing id",
        ):
            await client.fetch_payment("pay_001")

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_fetch_payment_rejects_invalid_order_id():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "id": "pay_001",
                "amount": 450000,
                "currency": "INR",
                "status": "captured",
                "order_id": 123,
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayResponseError,
            match="invalid order_id",
        ):
            await client.fetch_payment("pay_001")

    finally:
        await client.close()
        await async_client.aclose()


# Refund


@pytest.mark.asyncio
async def test_refund_payment():
    async def handler(request: httpx.Request):
        assert request.method == "POST"

        assert str(request.url) == (
            "https://api.razorpay.com/v1/payments/pay_001/refund"
        )

        assert request.headers["x-refund-idempotency"] == "refund_key_001"

        payload = json.loads(request.content.decode("utf-8"))

        assert payload == {
            "amount": 450000,
            "receipt": "refund_txn_001",
        }

        return httpx.Response(
            200,
            json={
                "id": "rfnd_001",
                "payment_id": "pay_001",
                "amount": 450000,
                "currency": "INR",
                "status": "processed",
            },
        )

    client, async_client = make_client(handler)

    try:
        result = await client.refund_payment(
            payment_id="pay_001",
            amount_paise=450000,
            idempotency_key="refund_key_001",
            receipt="refund_txn_001",
        )

        assert isinstance(
            result,
            RazorpayRefundResult,
        )

        assert result.refund_id == "rfnd_001"
        assert result.payment_id == "pay_001"
        assert result.amount_paise == 450000
        assert result.currency == "INR"
        assert result.status == "processed"

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_payment_without_optional_amount():
    async def handler(request: httpx.Request):
        payload = json.loads(request.content.decode("utf-8"))

        assert payload == {}

        return httpx.Response(
            200,
            json={
                "id": "rfnd_001",
                "payment_id": "pay_001",
                "amount": 450000,
                "currency": "INR",
                "status": "processed",
            },
        )

    client, async_client = make_client(handler)

    try:
        result = await client.refund_payment(
            payment_id="pay_001",
        )

        assert isinstance(
            result,
            RazorpayRefundResult,
        )

        assert result.refund_id == "rfnd_001"

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_rejects_empty_payment_id():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="payment_id cannot be empty",
        ):
            await client.refund_payment(
                payment_id="   ",
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_rejects_non_positive_amount():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="amount_paise must be positive",
        ):
            await client.refund_payment(
                payment_id="pay_001",
                amount_paise=0,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_rejects_short_idempotency_key():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="at least 10 characters",
        ):
            await client.refund_payment(
                payment_id="pay_001",
                idempotency_key="short",
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_rejects_invalid_idempotency_key_characters():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="invalid characters",
        ):
            await client.refund_payment(
                payment_id="pay_001",
                idempotency_key="refund key 001",
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_rejects_long_receipt():
    async def handler(request: httpx.Request):
        raise AssertionError("Network request should not be made")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            ValueError,
            match="40 characters",
        ):
            await client.refund_payment(
                payment_id="pay_001",
                receipt="x" * 41,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_rejects_malformed_response():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "payment_id": "pay_001",
                "amount": 450000,
                "currency": "INR",
                "status": "processed",
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayResponseError,
            match="missing id",
        ):
            await client.refund_payment(
                payment_id="pay_001",
            )

    finally:
        await client.close()
        await async_client.aclose()


# Error classification


@pytest.mark.asyncio
async def test_network_timeout_becomes_network_error():
    async def handler(request: httpx.Request):
        raise httpx.ReadTimeout("simulated timeout")

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayNetworkError,
            match="Could not determine",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_becomes_rate_limit_error():
    async def handler(request: httpx.Request):
        return httpx.Response(
            429,
            json={
                "error": {
                    "description": "Too many requests",
                }
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayRateLimitError,
            match="Too many requests",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_authentication_error_is_normalized():
    async def handler(request: httpx.Request):
        return httpx.Response(
            401,
            json={
                "error": {
                    "description": "Authentication failed",
                }
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayAuthenticationError,
            match="Authentication failed",
        ):
            await client.fetch_payment("pay_001")

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_bad_request_is_normalized():
    async def handler(request: httpx.Request):
        return httpx.Response(
            400,
            json={
                "error": {
                    "description": "Invalid request",
                }
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayBadRequestError,
            match="Invalid request",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_conflict_becomes_conflict_error():
    async def handler(request: httpx.Request):
        return httpx.Response(
            409,
            json={
                "error": {
                    "description": ("Request is still being processed"),
                }
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayConflictError,
            match="still being processed",
        ):
            await client.refund_payment(
                payment_id="pay_001",
                idempotency_key="refund_key_001",
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_server_error_becomes_razorpay_error():
    async def handler(request: httpx.Request):
        return httpx.Response(
            500,
            json={
                "error": {
                    "description": "Internal server error",
                }
            },
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayError,
            match="Internal server error",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_invalid_json_response_becomes_response_error():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            content=b"not-json",
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayResponseError,
            match="invalid JSON",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


@pytest.mark.asyncio
async def test_non_object_response_becomes_response_error():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json=[
                "unexpected",
                "response",
            ],
        )

    client, async_client = make_client(handler)

    try:
        with pytest.raises(
            RazorpayResponseError,
            match="JSON object",
        ):
            await client.create_order(
                amount_paise=450000,
            )

    finally:
        await client.close()
        await async_client.aclose()


# HTTP client ownership


@pytest.mark.asyncio
async def test_supplied_http_client_is_not_closed():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "id": "order_001",
                "amount": 450000,
                "currency": "INR",
                "status": "created",
            },
        )

    transport = httpx.MockTransport(handler)

    async_client = httpx.AsyncClient(
        transport=transport,
    )

    client = RazorpayClient(
        key_id="rzp_test_key",
        key_secret="test_secret",
        client=async_client,
    )

    try:
        result = await client.create_order(
            amount_paise=450000,
        )

        assert result.order_id == "order_001"

        await client.close()

        assert async_client.is_closed is False

    finally:
        await async_client.aclose()


# Pydantic normalized models


def test_razorpay_order_result_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RazorpayOrderResult.model_validate(
            {
                "order_id": "order_001",
                "amount_paise": 450000,
                "currency": "INR",
                "status": "created",
                "unexpected": True,
                "raw": {},
            }
        )


def test_razorpay_order_result_rejects_invalid_amount():
    with pytest.raises(ValidationError):
        RazorpayOrderResult.model_validate(
            {
                "order_id": "order_001",
                "amount_paise": 0,
                "currency": "INR",
                "status": "created",
                "raw": {},
            }
        )


def test_razorpay_payment_result_rejects_invalid_amount():
    with pytest.raises(ValidationError):
        RazorpayPaymentResult.model_validate(
            {
                "payment_id": "pay_001",
                "order_id": "order_001",
                "amount_paise": 0,
                "currency": "INR",
                "status": "captured",
                "raw": {},
            }
        )


def test_razorpay_refund_result_rejects_invalid_amount():
    with pytest.raises(ValidationError):
        RazorpayRefundResult.model_validate(
            {
                "refund_id": "rfnd_001",
                "payment_id": "pay_001",
                "amount_paise": -1,
                "currency": "INR",
                "status": "processed",
                "raw": {},
            }
        )
