from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine.idempotency import WALIdempotencyStore


def test_ten_concurrent_requests_have_exactly_one_winner(
    tmp_path: Path,
):
    db_path = tmp_path / "concurrency.db"

    store = WALIdempotencyStore(db_path)

    def attempt(request_number: int) -> bool:
        # Each thread gets its own store connection instance.
        # They all target the same SQLite database.
        thread_store = WALIdempotencyStore(db_path)

        return thread_store.acquire(
            idempotency_key="same-execution-key",
            transaction_id=f"txn_{request_number}",
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(
            executor.map(
                attempt,
                range(10),
            )
        )

    winners = sum(results)

    assert winners == 1

    record = store.get(
        "same-execution-key"
    )

    assert record is not None
    assert record.transaction_id.startswith("txn_")