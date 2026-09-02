from pathlib import Path

import pytest

from engine.catalog import (
    CatalogError,
    SQLiteCatalog,
)
from models.catalog import CatalogProduct


def make_product(
    *,
    sku: str = "shoe_001",
    merchant_id: str = "merchant_001",
    category: str = "footwear",
    price_paise: int = 450000,
    currency: str = "INR",
    stock: int = 20,
) -> CatalogProduct:
    return CatalogProduct(
        merchant_id=merchant_id,
        sku=sku,
        name="Running Shoes",
        category=category,
        price_paise=price_paise,
        currency=currency,
        stock=stock,
    )


def test_catalog_product_is_strict():
    product = make_product()

    assert product.sku == "shoe_001"
    assert product.price_paise == 450000
    assert product.currency == "INR"


def test_create_and_get_product(tmp_path: Path):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    product = make_product()

    catalog.create(product)

    loaded = catalog.get("shoe_001")

    assert loaded == product


def test_missing_product_returns_none(tmp_path: Path):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    assert catalog.get("missing") is None


def test_duplicate_sku_is_rejected(tmp_path: Path):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    catalog.create(make_product())

    with pytest.raises(
        CatalogError,
        match="already exists",
    ):
        catalog.create(make_product())


def test_list_by_merchant(tmp_path: Path):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    catalog.create(
        make_product(
            sku="shoe_002",
        )
    )

    catalog.create(
        make_product(
            sku="shoe_001",
        )
    )

    catalog.create(
        make_product(
            sku="coffee_001",
            merchant_id="merchant_002",
            category="grocery",
            price_paise=40000,
        )
    )

    products = catalog.list_by_merchant(
        "merchant_001"
    )

    assert [product.sku for product in products] == [
        "shoe_001",
        "shoe_002",
    ]


def test_catalog_preserves_server_authoritative_price(
    tmp_path: Path,
):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    product = make_product(
        price_paise=450000,
    )

    catalog.create(product)

    loaded = catalog.get("shoe_001")

    assert loaded is not None
    assert loaded.price_paise == 450000


def test_catalog_preserves_server_authoritative_merchant(
    tmp_path: Path,
):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    product = make_product(
        merchant_id="merchant_001",
    )

    catalog.create(product)

    loaded = catalog.get("shoe_001")

    assert loaded is not None
    assert loaded.merchant_id == "merchant_001"


def test_catalog_preserves_server_authoritative_category(
    tmp_path: Path,
):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    product = make_product(
        category="footwear",
    )

    catalog.create(product)

    loaded = catalog.get("shoe_001")

    assert loaded is not None
    assert loaded.category == "footwear"


def test_catalog_supports_zero_stock(
    tmp_path: Path,
):
    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )

    catalog.create(
        make_product(stock=0)
    )

    loaded = catalog.get("shoe_001")

    assert loaded is not None
    assert loaded.stock == 0


def test_negative_stock_is_rejected():
    with pytest.raises(ValueError):
        make_product(stock=-1)


def test_zero_price_is_rejected():
    with pytest.raises(ValueError):
        make_product(price_paise=0)