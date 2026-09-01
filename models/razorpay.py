from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
)

class RazorpayOrderResult(BaseModel):
    """
    Normalized Razorpay order response.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    order_id: StrictStr = Field(
        min_length=1,
    )

    amount_paise: StrictInt = Field(
        gt=0,
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
    )

    status: StrictStr = Field(
        min_length=1,
    )

    raw: dict[str, Any]


class RazorpayPaymentResult(BaseModel):
    """
    Normalized Razorpay payment response.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    payment_id: StrictStr = Field(
        min_length=1,
    )

    order_id: StrictStr | None = None

    amount_paise: StrictInt = Field(
        gt=0,
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
    )

    status: StrictStr = Field(
        min_length=1,
    )

    raw: dict[str, Any]


class RazorpayRefundResult(BaseModel):
    """
    Normalized Razorpay refund response.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    refund_id: StrictStr = Field(
        min_length=1,
    )

    payment_id: StrictStr = Field(
        min_length=1,
    )

    amount_paise: StrictInt = Field(
        gt=0,
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
    )

    status: StrictStr = Field(
        min_length=1,
    )

    raw: dict[str, Any]
