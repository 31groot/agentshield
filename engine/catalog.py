from __future__ import annotations

import sqlite3

from models.catalog import CatalogProduct


class CatalogError(Exception):
    """Raised when catalog state cannot be safely accessed."""


class SQLiteCatalog:
    """
    Server-owned product catalog backed by SQLite WAL.

    The catalog stores factual product information only.
    It does not authorize transactions.
    """

    def __init__(self, db_path: str) -> None:
        if not db_path or not db_path.strip():
            raise ValueError("db_path cannot be empty")

        self._db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()

        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_products (
                    sku TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price_paise INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    stock INTEGER NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_catalog_products_merchant
                ON catalog_products(merchant_id)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_catalog_products_category
                ON catalog_products(category)
                """
            )
        finally:
            connection.close()

    def create(
        self,
        product: CatalogProduct,
    ) -> CatalogProduct:
        """
        Persist a new catalog product.

        An existing SKU cannot be silently overwritten.
        """

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            connection.execute(
                """
                INSERT INTO catalog_products (
                    sku,
                    merchant_id,
                    name,
                    category,
                    price_paise,
                    currency,
                    stock
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product.sku,
                    product.merchant_id,
                    product.name,
                    product.category,
                    product.price_paise,
                    product.currency,
                    product.stock,
                ),
            )

            connection.execute("COMMIT")
            return product

        except sqlite3.IntegrityError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise CatalogError(
                "Catalog SKU already exists"
            ) from exc

        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise CatalogError(
                "Failed to create catalog product"
            ) from exc

        finally:
            connection.close()

    def get(
        self,
        sku: str,
    ) -> CatalogProduct | None:
        """
        Return the authoritative product for a SKU.
        """

        if not sku:
            raise ValueError("sku cannot be empty")

        connection = self._connect()

        try:
            row = connection.execute(
                """
                SELECT
                    sku,
                    merchant_id,
                    name,
                    category,
                    price_paise,
                    currency,
                    stock
                FROM catalog_products
                WHERE sku = ?
                """,
                (sku,),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_model(row)

        except Exception as exc:
            raise CatalogError(
                "Failed to read catalog product"
            ) from exc

        finally:
            connection.close()

    def list_by_merchant(
        self,
        merchant_id: str,
    ) -> list[CatalogProduct]:
        """
        Return products owned by one merchant.
        """

        if not merchant_id:
            raise ValueError("merchant_id cannot be empty")

        connection = self._connect()

        try:
            rows = connection.execute(
                """
                SELECT
                    sku,
                    merchant_id,
                    name,
                    category,
                    price_paise,
                    currency,
                    stock
                FROM catalog_products
                WHERE merchant_id = ?
                ORDER BY sku
                """,
                (merchant_id,),
            ).fetchall()

            return [
                self._row_to_model(row)
                for row in rows
            ]

        except Exception as exc:
            raise CatalogError(
                "Failed to list merchant catalog"
            ) from exc

        finally:
            connection.close()

    @staticmethod
    def _row_to_model(
        row: sqlite3.Row,
    ) -> CatalogProduct:
        return CatalogProduct(
            merchant_id=str(row["merchant_id"]),
            sku=str(row["sku"]),
            name=str(row["name"]),
            category=str(row["category"]),
            price_paise=int(row["price_paise"]),
            currency=str(row["currency"]),
            stock=int(row["stock"]),
        )