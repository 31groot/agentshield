from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.transaction_store import (
    SQLiteTransactionStore,
    TransactionStoreError,
)
from models.intent import IntentItem
from models.transaction import (
    TransactionRecord,
    TransactionState,
)


def make_transaction(
    *,
    state: TransactionState = TransactionState.CREATED,
    razorpay_order_id: str | None = "order_001",
    razorpay_payment_id: str | None = None,
    **overrides,
) -> TransactionRecord:
    now = datetime.now(timezone.utc)

    payload = {
        "transaction_id": "txn_001",
        "intent_id": "intent_001",
        "user_id": "user_123",
        "agent_id": "agent_001",
        "merchant_id": "merchant_001",
        "amount_paise": 450000,
        "currency": "INR",
        "items": [
            IntentItem(
                sku="shoe_001",
                quantity=1,
            ),
            IntentItem(
                sku="lace_001",
                quantity=2,
            ),
        ],
        "intent_hash": "a" * 64,
        "idempotency_key": "exec_001",
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "state": state,
        "created_at": now,
        "updated_at": now,
    }

    payload.update(overrides)

    return TransactionRecord.model_validate(
        payload
    )


def make_store(
    tmp_path: Path,
) -> SQLiteTransactionStore:
    return SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )


def test_create_and_get_round_trips_transaction(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    result = store.create(transaction)

    assert result == transaction

    stored = store.get("txn_001")

    assert stored == transaction
    assert stored is not None
    assert stored.items == transaction.items
    assert stored.state == TransactionState.CREATED


def test_missing_transaction_returns_none(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    assert store.get("missing") is None


def test_get_by_order_id_returns_transaction(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    store.create(transaction)

    stored = store.get_by_order_id(
        "order_001"
    )

    assert stored == transaction
    assert stored is not None
    assert stored.transaction_id == "txn_001"


def test_get_by_order_id_returns_none_when_missing(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    assert store.get_by_order_id(
        "order_missing"
    ) is None


def test_get_by_payment_id_returns_transaction(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction(
        razorpay_payment_id="pay_001",
    )

    store.create(transaction)

    stored = store.get_by_payment_id(
        "pay_001"
    )

    assert stored == transaction
    assert stored is not None
    assert stored.transaction_id == "txn_001"


def test_get_by_payment_id_returns_none_when_missing(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    assert store.get_by_payment_id(
        "pay_missing"
    ) is None


def test_update_transaction_state(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    store.create(transaction)

    updated = transaction.model_copy(
        update={
            "state": TransactionState.DISPATCHED,
            "razorpay_order_id": "order_002",
            "updated_at": datetime.now(timezone.utc),
        }
    )

    result = store.update(updated)

    assert result == updated

    stored = store.get("txn_001")

    assert stored is not None
    assert stored.state == TransactionState.DISPATCHED
    assert stored.razorpay_order_id == "order_002"


def test_update_transaction_payment_id(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    store.create(transaction)

    updated = transaction.model_copy(
        update={
            "razorpay_payment_id": "pay_001",
            "state": TransactionState.SUCCESS,
            "updated_at": datetime.now(timezone.utc),
        }
    )

    store.update(updated)

    stored = store.get("txn_001")

    assert stored is not None
    assert stored.razorpay_payment_id == "pay_001"
    assert stored.state == TransactionState.SUCCESS


def test_update_missing_transaction_is_rejected(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    with pytest.raises(
        TransactionStoreError,
        match="does not exist",
    ):
        store.update(transaction)


def test_duplicate_transaction_id_is_rejected(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    store.create(transaction)

    with pytest.raises(
        TransactionStoreError,
        match="already exists|unique",
    ):
        store.create(transaction)


def test_duplicate_idempotency_key_is_rejected(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    first = make_transaction()

    second = make_transaction(
        transaction_id="txn_002",
        intent_id="intent_002",
    )

    store.create(first)

    with pytest.raises(
        TransactionStoreError,
        match="already exists|unique",
    ):
        store.create(second)


def test_duplicate_order_id_is_rejected(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    first = make_transaction()

    second = make_transaction(
        transaction_id="txn_002",
        intent_id="intent_002",
    )

    store.create(first)

    with pytest.raises(
        TransactionStoreError,
        match="already exists|unique",
    ):
        store.create(second)


def test_duplicate_payment_id_is_rejected(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    first = make_transaction(
        razorpay_payment_id="pay_001",
    )

    second = make_transaction(
        transaction_id="txn_002",
        intent_id="intent_002",
        razorpay_payment_id="pay_001",
    )

    store.create(first)

    with pytest.raises(
        TransactionStoreError,
        match="already exists|unique",
    ):
        store.create(second)


def test_transaction_persists_across_store_instances(
    tmp_path: Path,
):
    db_path = tmp_path / "transactions.db"

    first_store = SQLiteTransactionStore(
        db_path
    )

    transaction = make_transaction()

    first_store.create(transaction)

    second_store = SQLiteTransactionStore(
        db_path
    )

    stored = second_store.get(
        "txn_001"
    )

    assert stored == transaction


def test_items_round_trip_with_per_sku_quantities(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction()

    store.create(transaction)

    stored = store.get("txn_001")

    assert stored is not None
    assert [
        (item.sku, item.quantity)
        for item in stored.items
    ] == [
        ("shoe_001", 1),
        ("lace_001", 2),
    ]


def test_transaction_fields_round_trip(
    tmp_path: Path,
):
    store = make_store(tmp_path)

    transaction = make_transaction(
        amount_paise=725000,
        currency="USD",
        state=TransactionState.UNKNOWN,
        razorpay_order_id=None,
        razorpay_payment_id="pay_009",
    )

    store.create(transaction)

    stored = store.get("txn_001")

    assert stored is not None
    assert stored.amount_paise == 725000
    assert stored.currency == "USD"
    assert stored.state == TransactionState.UNKNOWN
    assert stored.razorpay_order_id is None
    assert stored.razorpay_payment_id == "pay_009"


@pytest.mark.parametrize(
    ("method", "value", "field_name"),
    [
        (
            "get",
            "",
            "transaction_id",
        ),
        (
            "get_by_order_id",
            "",
            "order_id",
        ),
        (
            "get_by_payment_id",
            "",
            "payment_id",
        ),
    ],
)
def test_lookup_rejects_empty_identifier(
    tmp_path: Path,
    method: str,
    value: str,
    field_name: str,
):
    store = make_store(tmp_path)

    with pytest.raises(
        ValueError,
        match=f"{field_name} cannot be empty",
    ):
        getattr(store, method)(value)

