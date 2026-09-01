from __future__ import annotations

from typing import Any

from models.razorpay import (
    RazorpayOrderResult,
    RazorpayPaymentResult,
    RazorpayRefundResult,
)

import httpx

import re


class RazorpayError(Exception):
    """
    Base exception for Razorpay adapter failures.
    """


class RazorpayAuthenticationError(RazorpayError):
    """
    Raised when Razorpay rejects API credentials.
    """


class RazorpayBadRequestError(RazorpayError):
    """
    Raised when Razorpay rejects the request.
    """


class RazorpayConflictError(RazorpayError):
    """
    Raised when Razorpay reports a conflicting or in-progress operation.
    """


class RazorpayRateLimitError(RazorpayError):
    """
    Raised when Razorpay rate-limits the request.
    """


class RazorpayNetworkError(RazorpayError):
    """
    Raised when AgentShield cannot determine whether
    Razorpay received the request.
    """


class RazorpayResponseError(RazorpayError):
    """
    Raised when Razorpay returns a malformed or unusable response.
    """

class RazorpayClient:
    """
    Thin Razorpay REST API adapter.

    Responsibilities:
    - authenticate with Razorpay
    - create orders
    - fetch payments
    - create refunds
    - normalize external responses
    - classify transport/API failures

    """

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        base_url: str = "https://api.razorpay.com/v1",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not key_id.strip():
            raise ValueError("key_id cannot be empty")

        if not key_secret.strip():
            raise ValueError("key_secret cannot be empty")

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )

        self._key_id = key_id
        self._key_secret = key_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "RazorpayClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                auth=(
                    self._key_id,
                    self._key_secret,
                ),
            )

        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """
        Close the internally-owned HTTP client.

        """

        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_order(
        self,
        *,
        amount_paise: int,
        currency: str = "INR",
        receipt: str | None = None,
        notes: dict[str, str] | None = None,
    ) -> RazorpayOrderResult:
        """
        Create a Razorpay order.
        """

        if amount_paise <= 0:
            raise ValueError(
                "amount_paise must be positive"
            )

        payload: dict[str, Any] = {
            "amount": amount_paise,
            "currency": currency,
        }

        if receipt is not None:
            self._validate_receipt(receipt)
            payload["receipt"] = receipt

        if notes is not None:
            self._validate_notes(notes)
            payload["notes"] = notes

        response = await self._request(
            method="POST",
            path="/orders",
            json=payload,
        )

        order_id = self._require_string(
            response,
            "id",
            "Razorpay order response missing id",
        )

        amount = self._require_positive_int(
            response,
            "amount",
            "Razorpay order response contains invalid amount",
        )

        response_currency = self._require_string(
            response,
            "currency",
            "Razorpay order response missing currency",
        )

        status = self._require_string(
            response,
            "status",
            "Razorpay order response missing status",
        )

        return RazorpayOrderResult(
            order_id=order_id,
            amount_paise=amount,
            currency=response_currency,
            status=status,
            raw=response,
        )

    async def fetch_payment(
        self,
        payment_id: str,
    ) -> RazorpayPaymentResult:
        """
        Fetch a Razorpay payment by ID.

        """

        if not payment_id.strip():
            raise ValueError(
                "payment_id cannot be empty"
            )

        response = await self._request(
            method="GET",
            path=f"/payments/{payment_id}",
        )

        returned_payment_id = self._require_string(
            response,
            "id",
            "Razorpay payment response missing id",
        )

        order_id = response.get("order_id")

        if order_id is not None:
            if not isinstance(order_id, str):
                raise RazorpayResponseError(
                    "Razorpay payment response contains invalid order_id"
                )

            if not order_id.strip():
                raise RazorpayResponseError(
                    "Razorpay payment response contains empty order_id"
                )

        amount = self._require_positive_int(
            response,
            "amount",
            "Razorpay payment response contains invalid amount",
        )

        currency = self._require_string(
            response,
            "currency",
            "Razorpay payment response missing currency",
        )

        status = self._require_string(
            response,
            "status",
            "Razorpay payment response missing status",
        )

        return RazorpayPaymentResult(
            payment_id=returned_payment_id,
            order_id=order_id,
            amount_paise=amount,
            currency=currency,
            status=status,
            raw=response,
        )

    async def refund_payment(
        self,
        *,
        payment_id: str,
        amount_paise: int | None = None,
        idempotency_key: str | None = None,
        receipt: str | None = None,
    ) -> RazorpayRefundResult:
        """
        Create a Razorpay refund.

        """

        if not payment_id.strip():
            raise ValueError(
                "payment_id cannot be empty"
            )

        if amount_paise is not None and amount_paise <= 0:
            raise ValueError(
                "amount_paise must be positive"
            )

        headers: dict[str, str] = {}

        if idempotency_key is not None:
            self._validate_refund_idempotency_key(
                idempotency_key
            )

            headers["X-Refund-Idempotency"] = idempotency_key

        payload: dict[str, Any] = {}

        if amount_paise is not None:
            payload["amount"] = amount_paise

        if receipt is not None:
            self._validate_receipt(receipt)
            payload["receipt"] = receipt

        response = await self._request(
            method="POST",
            path=f"/payments/{payment_id}/refund",
            json=payload,
            headers=headers,
        )

        refund_id = self._require_string(
            response,
            "id",
            "Razorpay refund response missing id",
        )

        returned_payment_id = self._require_string(
            response,
            "payment_id",
            "Razorpay refund response missing payment_id",
        )

        amount = self._require_positive_int(
            response,
            "amount",
            "Razorpay refund response contains invalid amount",
        )

        currency = self._require_string(
            response,
            "currency",
            "Razorpay refund response missing currency",
        )

        status = self._require_string(
            response,
            "status",
            "Razorpay refund response missing status",
        )

        return RazorpayRefundResult(
            refund_id=refund_id,
            payment_id=returned_payment_id,
            amount_paise=amount,
            currency=currency,
            status=status,
            raw=response,
        )

    async def _request(
        self,
        *,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Perform one authenticated Razorpay API request.
        
        """

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                auth=(
                    self._key_id,
                    self._key_secret,
                ),
            )

        try:
            response = await self._client.request(
                method=method,
                url=f"{self._base_url}{path}",
                json=json,
                headers=headers,
                auth=(
                    self._key_id,
                    self._key_secret,
                ),
            )

        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as exc:
            raise RazorpayNetworkError(
                "Could not determine Razorpay request outcome"
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise RazorpayResponseError(
                "Razorpay returned invalid JSON"
            ) from exc

        if not isinstance(body, dict):
            raise RazorpayResponseError(
                "Razorpay response must be a JSON object"
            )

        if response.status_code in {401, 403}:
            raise RazorpayAuthenticationError(
                self._error_message(body)
            )

        if response.status_code == 409:
            raise RazorpayConflictError(
                self._error_message(body)
            )

        if response.status_code == 429:
            raise RazorpayRateLimitError(
                self._error_message(body)
            )

        if 400 <= response.status_code < 500:
            raise RazorpayBadRequestError(
                self._error_message(body)
            )

        if response.status_code >= 500:
            raise RazorpayError(
                self._error_message(body)
            )

        return body

    @staticmethod
    def _validate_receipt(
        receipt: str,
    ) -> None:
        if not receipt.strip():
            raise ValueError(
                "receipt cannot be empty"
            )

        if len(receipt) > 40:
            raise ValueError(
                "receipt cannot exceed 40 characters"
            )

        try:
            receipt.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(
                "receipt must contain only supported ASCII characters"
            ) from exc

    @staticmethod
    def _validate_notes(
        notes: dict[str, str],
    ) -> None:
        if len(notes) > 15:
            raise ValueError(
                "notes cannot contain more than 15 entries"
            )

        for key, value in notes.items():
            if not isinstance(key, str):
                raise ValueError(
                    "note keys must be strings"
                )

            if not isinstance(value, str):
                raise ValueError(
                    "note values must be strings"
                )

            if len(key) > 255:
                raise ValueError(
                    "note keys cannot exceed 255 characters"
                )

            if len(value) > 512:
                raise ValueError(
                    "note values cannot exceed 512 characters"
                )

    @staticmethod
    def _validate_refund_idempotency_key(
        value: str,
    ) -> None:
        if len(value) < 10:
            raise ValueError(
                "refund idempotency key must be at least 10 characters"
            )

        if not re.fullmatch(
            r"[A-Za-z0-9_-]+",
            value,
        ):
            raise ValueError(
                "refund idempotency key contains invalid characters; "
                "only letters, numbers, hyphens, and underscores are allowed"
            )

    @staticmethod
    def _error_message(
        body: dict[str, Any],
    ) -> str:
        error = body.get("error")

        if isinstance(error, dict):
            description = error.get("description")

            if (
                isinstance(description, str)
                and description.strip()
            ):
                return description

        return "Razorpay API request failed"

    @staticmethod
    def _require_string(
        payload: dict[str, Any],
        key: str,
        message: str,
    ) -> str:
        value = payload.get(key)

        if not isinstance(value, str) or not value.strip():
            raise RazorpayResponseError(message)

        return value

    @staticmethod
    def _require_positive_int(
        payload: dict[str, Any],
        key: str,
        message: str,
    ) -> int:
        value = payload.get(key)

        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
        ):
            raise RazorpayResponseError(message)

        return value