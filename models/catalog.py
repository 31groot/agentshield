from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
)


class CatalogProduct(BaseModel):
    """
    Server-owned authoritative product record.

    The catalog describes factual merchant/product data.
    It does not decide whether a transaction is authorized.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    merchant_id: StrictStr = Field(
        min_length=1,
        description="Merchant that owns this product.",
    )

    sku: StrictStr = Field(
        min_length=1,
        description="Unique product SKU within the catalog.",
    )

    name: StrictStr = Field(
        min_length=1,
        description="Human-readable product name.",
    )

    category: StrictStr = Field(
        min_length=1,
        description="Server-owned product category.",
    )

    price_paise: StrictInt = Field(
        gt=0,
        description="Authoritative product price in paise.",
    )

    currency: StrictStr = Field(
        min_length=3,
        max_length=3,
        description="Authoritative catalog currency.",
    )

    stock: StrictInt = Field(
        ge=0,
        description="Current available stock units.",
    )