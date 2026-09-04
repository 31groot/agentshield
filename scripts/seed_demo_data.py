from __future__ import annotations

from dotenv import load_dotenv

from config import Settings
from engine.authorization import SQLiteAuthorizationAuthority
from engine.catalog import SQLiteCatalog
from models.authorization import AgentAuthorization
from models.catalog import CatalogProduct


def main() -> None:
    load_dotenv()

    settings = Settings.from_environment()

    authorization_authority = SQLiteAuthorizationAuthority(
        f"{settings.database_path}.authorization",
    )

    catalog = SQLiteCatalog(
        f"{settings.database_path}.catalog",
    )

    authorization = AgentAuthorization(
        user_id=settings.api_user_id,
        agent_id=settings.api_agent_id,
        authorization_id="demo-auth-001",
        active=True,
        revoked=False,
        max_amount_paise=500000,
        allowed_merchants=["merchant_001"],
        allowed_categories=["footwear"],
        allowed_skus=["shoe_001"],
        max_quantity=2,
        currency="INR",
    )

    existing_authorization = authorization_authority.get(
        authorization.authorization_id,
    )

    if existing_authorization is None:
        authorization_authority.create(
            authorization,
        )
        print("Created demo authorization: demo-auth-001")
    elif existing_authorization != authorization:
        raise RuntimeError(
            "demo-auth-001 already exists with different bounds"
        )
    else:
        print("Demo authorization already exists")

    product = CatalogProduct(
        merchant_id="merchant_001",
        sku="shoe_001",
        name="AgentShield Running Shoe",
        category="footwear",
        price_paise=450000,
        currency="INR",
        stock=10,
    )

    existing_product = catalog.get(product.sku)

    if existing_product is None:
        catalog.create(product)
        print("Created demo catalog product: shoe_001")
    elif existing_product != product:
        raise RuntimeError(
            "shoe_001 already exists with different catalog facts"
        )
    else:
        print("Demo catalog product already exists")

    print()
    print("Demo data ready")
    print("Authorization: demo-auth-001")
    print("Merchant: merchant_001")
    print("SKU: shoe_001")
    print("Price: ₹4,500")
    print("Maximum authorization: ₹5,000")
    print("Maximum quantity: 2")
    print("Stock: 10")


if __name__ == "__main__":
    main()
