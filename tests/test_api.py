from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_audit_trail, get_orchestrator, get_transaction_store
from api.main import create_app
from models.mandate import Mandate
from models.orchestration import OrchestrationResult
from models.transaction import TransactionRecord, TransactionState


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        now = datetime.now(timezone.utc)
        transaction = TransactionRecord.model_construct(
            transaction_id=kwargs["transaction_id"],
            intent_id=kwargs["intent_id"],
            user_id=kwargs["user_id"],
            agent_id=kwargs["agent_id"],
            merchant_id="merchant_001",
            amount_paise=450000,
            currency="INR",
            items=[],
            intent_hash="a" * 64,
            idempotency_key=kwargs["idempotency_key"],
            state=TransactionState.DISPATCHED,
            razorpay_order_id="order_001",
            razorpay_payment_id=None,
            created_at=now,
            updated_at=now,
        )
        mandate = Mandate.model_construct(
            user_id=kwargs["user_id"],
            agent_id=kwargs["agent_id"],
            merchant_id="merchant_001",
            amount_paise=450000,
            intent_hash="a" * 64,
            nonce="nonce_001",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            signature="b" * 64,
        )
        return OrchestrationResult(
            transaction=transaction,
            mandate=mandate,
            status="DISPATCHED",
        )


class FakeTransactionStore:
    def __init__(self, transaction: TransactionRecord | None = None) -> None:
        self.transaction = transaction

    def get(self, transaction_id: str):
        if (
            self.transaction is not None
            and self.transaction.transaction_id == transaction_id
        ):
            return self.transaction
        return None


class FakeAuditTrail:
    def __init__(self) -> None:
        self.events = []

    def list_events(self, *, transaction_id: str | None = None):
        return self.events


def build_client():
    app = create_app()
    orchestrator = FakeOrchestrator()
    transaction_store = FakeTransactionStore()
    audit_trail = FakeAuditTrail()

    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_transaction_store] = lambda: transaction_store
    app.dependency_overrides[get_audit_trail] = lambda: audit_trail

    return app, orchestrator, transaction_store, audit_trail


def test_health_endpoint():
    app, _, _, _ = build_client()
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_execute_requires_idempotency_key():
    app, _, _, _ = build_client()
    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            json={
                "user_message": "Buy groceries under ₹2000.",
                "user_id": "user_123",
                "agent_id": "agent_001",
            },
        )

    assert response.status_code == 422


def test_execute_rejects_unknown_request_field():
    app, _, _, _ = build_client()
    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={"Idempotency-Key": "exec_001"},
            json={
                "user_message": "Buy groceries under ₹2000.",
                "user_id": "user_123",
                "agent_id": "agent_001",
                "amount": 200000,
            },
        )

    assert response.status_code == 422


def test_execute_generates_server_owned_ids_and_forwards_request():
    app, orchestrator, _, _ = build_client()
    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={"Idempotency-Key": "exec_001"},
            json={
                "user_message": "Buy groceries under ₹2000.",
                "user_id": "user_123",
                "agent_id": "agent_001",
                "merchant_context": {"merchant_id": "merchant_001"},
            },
        )

    assert response.status_code == 200
    assert len(orchestrator.calls) == 1
    call = orchestrator.calls[0]
    assert call["user_message"] == "Buy groceries under ₹2000."
    assert call["user_id"] == "user_123"
    assert call["agent_id"] == "agent_001"
    assert call["idempotency_key"] == "exec_001"
    assert str(call["intent_id"]).startswith("intent_")
    assert str(call["transaction_id"]).startswith("txn_")
    assert response.json()["status"] == "DISPATCHED"


def test_transaction_endpoint_returns_404_when_missing():
    app, _, _, _ = build_client()
    with TestClient(app) as client:
        response = client.get("/v1/transactions/txn_missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Transaction not found"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "user_message": "   ",
            "user_id": "user_123",
            "agent_id": "agent_001",
        },
        {
            "user_message": "Buy groceries.",
            "user_id": "   ",
            "agent_id": "agent_001",
        },
    ],
)
def test_execute_rejects_blank_required_strings(payload):
    app, _, _, _ = build_client()
    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={"Idempotency-Key": "exec_001"},
            json=payload,
        )

    assert response.status_code == 422
