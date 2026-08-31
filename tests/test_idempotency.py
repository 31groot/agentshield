import pytest

from pathlib import Path

from engine.idempotency import WALIdempotencyStore
from models.transaction import IdempotencyStatus

def test_first_acquire_succeeds(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    acquired = store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_001",
    )

    assert acquired is True


def test_duplicate_acquire_fails(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    first = store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_001",
    )

    second = store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_002",
    )

    assert first is True
    assert second is False


def test_duplicate_does_not_replace_original_record(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_001",
    )

    store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_999",
    )

    record = store.get("idem_001")

    assert record is not None
    assert record.transaction_id == "txn_001"
    assert record.status == IdempotencyStatus.ACQUIRED


def test_get_missing_key_returns_none(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    assert store.get("does_not_exist") is None


def test_mark_completed(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_001",
    )

    updated = store.mark_completed(
        idempotency_key="idem_001"
    )

    assert updated is True

    record = store.get("idem_001")

    assert record is not None
    assert record.status == IdempotencyStatus.COMPLETED


def test_mark_failed_safe_to_retry(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_001",
    )

    updated = store.mark_failed_safe_to_retry(
        idempotency_key="idem_001"
    )

    assert updated is True

    record = store.get("idem_001")

    assert record is not None
    assert record.status == IdempotencyStatus.FAILED_SAFE_TO_RETRY


def test_mark_completed_missing_key_returns_false(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    assert store.mark_completed(
        idempotency_key="missing"
    ) is False


def test_mark_failed_missing_key_returns_false(tmp_path: Path):
    store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    assert store.mark_failed_safe_to_retry(
        idempotency_key="missing"
    ) is False

def test_record_persists_across_store_instances(tmp_path):
    db_path = tmp_path / "state.db"

    first_store = WALIdempotencyStore(db_path)

    first_store.acquire(
        idempotency_key="idem_001",
        transaction_id="txn_001",
    )

    second_store = WALIdempotencyStore(db_path)

    record = second_store.get("idem_001")

    assert record is not None
    assert record.idempotency_key == "idem_001"
    assert record.transaction_id == "txn_001"
    assert record.status == IdempotencyStatus.ACQUIRED

def test_blank_idempotency_key_is_rejected(tmp_path):
    store = WALIdempotencyStore(tmp_path / "state.db")

    with pytest.raises(ValueError):
        store.acquire(
            idempotency_key="   ",
            transaction_id="txn_001",
        )
def test_blank_transaction_id_is_rejected(tmp_path):
    store = WALIdempotencyStore(tmp_path / "state.db")

    with pytest.raises(ValueError):
        store.acquire(
            idempotency_key="idem_001",
            transaction_id="   ",
        )