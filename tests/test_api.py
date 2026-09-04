from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from models.intent import IntentItem
import pytest
from fastapi.testclient import TestClient
from api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    configure_app,
)
from api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_audit_trail,
    get_orchestrator,
    get_reconciliation_engine,
    get_transaction_store,
    get_webhook_handler,
)
from api.main import create_app
from engine.reconciliation import (
    ReconciliationEngine,
    WebhookEventStore,
)
from engine.transaction_store import SQLiteTransactionStore
from models.mandate import Mandate
from models.orchestration import OrchestrationResult
from models.transaction import TransactionRecord, TransactionState
from webhooks.razorpay import RazorpayWebhookHandler


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
    def __init__(
        self,
        transaction: TransactionRecord | None = None,
    ) -> None:
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

    def list_events(
        self,
        *,
        transaction_id: str | None = None,
    ):
        return self.events


class FakeReconciliationEngine:
    def __init__(
        self,
        transaction: TransactionRecord,
    ) -> None:
        self.transaction = transaction
        self.calls = []

    def reconcile_event(self, *, event):
        self.calls.append(event)
        return self.transaction


def build_client():
    app = create_app()

    orchestrator = FakeOrchestrator()
    transaction_store = FakeTransactionStore()
    audit_trail = FakeAuditTrail()

    app.dependency_overrides[get_orchestrator] = (
        lambda: orchestrator
    )
    app.dependency_overrides[get_transaction_store] = (
        lambda: transaction_store
    )
    app.dependency_overrides[get_audit_trail] = (
        lambda: audit_trail
    )
    app.dependency_overrides[get_authenticated_principal] = (
        lambda: AuthenticatedPrincipal(
            user_id="user_123",
            agent_id="agent_001",
        )
    )

    return (
        app,
        orchestrator,
        transaction_store,
        audit_trail,
    )

TEST_API_TOKEN = "12345678901234567890123456789012"


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TEST_API_TOKEN}",
    }

def signed_webhook_headers(
    raw_body: bytes,
    *,
    event_id: str = "evt_001",
) -> dict[str, str]:
    secret = b"test-webhook-secret"

    signature = hmac.new(
        secret,
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": event_id,
    }


def webhook_payload() -> dict[str, object]:
    return {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_001",
                    "order_id": "order_001",
                    "amount": 450000,
                    "currency": "INR",
                }
            }
        },
    }


def webhook_transaction() -> TransactionRecord:
    now = datetime.now(timezone.utc)

    return TransactionRecord(
        transaction_id="txn_001",
        intent_id="intent_001",
        user_id="user_123",
        agent_id="agent_001",
        merchant_id="merchant_001",
        amount_paise=450000,
        currency="INR",
        items=[
            IntentItem(
                sku="shoe_001",
                quantity=1,
            )
        ],
        authorization_snapshot=None,
        intent_hash="a" * 64,
        idempotency_key="exec_001",
        state=TransactionState.DISPATCHED,
        razorpay_order_id="order_001",
        razorpay_payment_id=None,
        created_at=now,
        updated_at=now,
    )
def build_webhook_client(
    reconciliation_engine,
):
    app = create_app()

    app.dependency_overrides[get_webhook_handler] = (
        lambda: RazorpayWebhookHandler(
            "test-webhook-secret",
        )
    )

    app.dependency_overrides[
        get_reconciliation_engine
    ] = lambda: reconciliation_engine

    return app


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
                "merchant_context": {
                    "merchant_id": "merchant_001"
                },
            },
        )

    assert response.status_code == 200
    assert len(orchestrator.calls) == 1

    call = orchestrator.calls[0]

    assert call["user_message"] == (
        "Buy groceries under ₹2000."
    )
    assert call["user_id"] == "user_123"
    assert call["agent_id"] == "agent_001"
    assert call["idempotency_key"] == "exec_001"
    assert str(call["intent_id"]).startswith("intent_")
    assert str(call["transaction_id"]).startswith("txn_")
    assert response.json()["status"] == "DISPATCHED"


def test_transaction_endpoint_returns_404_when_missing():
    app, _, _, _ = build_client()

    with TestClient(app) as client:
        response = client.get(
            "/v1/transactions/txn_missing"
        )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Transaction not found"
    )


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
def test_execute_rejects_blank_required_strings(
    payload,
):
    app, _, _, _ = build_client()

    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={"Idempotency-Key": "exec_001"},
            json=payload,
        )

    assert response.status_code == 422


def test_webhook_endpoint_verifies_signature_before_reconciliation():
    engine = FakeReconciliationEngine(
        webhook_transaction()
    )
    app = build_webhook_client(engine)

    raw_body = json.dumps(
        webhook_payload(),
        separators=(",", ":"),
    ).encode()

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers=signed_webhook_headers(raw_body),
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "PROCESSED",
        "event_id": "evt_001",
        "transaction_id": "txn_001",
        "transaction_state": "DISPATCHED",
    }

    assert len(engine.calls) == 1


def test_webhook_endpoint_rejects_invalid_signature_before_parsing():
    engine = FakeReconciliationEngine(
        webhook_transaction()
    )
    app = build_webhook_client(engine)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/razorpay",
            content=b"not-json",
            headers={
                "X-Razorpay-Signature": "invalid",
                "X-Razorpay-Event-Id": "evt_002",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Invalid webhook signature"
    )

    assert engine.calls == []


def test_webhook_endpoint_rejects_malformed_signed_payload():
    engine = FakeReconciliationEngine(
        webhook_transaction()
    )
    app = build_webhook_client(engine)

    raw_body = b"not-json"

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers=signed_webhook_headers(
                raw_body,
                event_id="evt_003",
            ),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Invalid webhook JSON"
    )

    assert engine.calls == []


def test_webhook_endpoint_deduplicates_persisted_event(
    tmp_path,
):
    transaction_store = SQLiteTransactionStore(
        str(tmp_path / "transactions.db")
    )

    transaction = webhook_transaction()
    transaction_store.create(transaction)

    event_store = WebhookEventStore(
        str(tmp_path / "webhooks.db")
    )

    engine = ReconciliationEngine(
        webhook_store=event_store,
        transaction_store=transaction_store,
    )

    app = build_webhook_client(engine)

    raw_body = json.dumps(
        webhook_payload(),
        separators=(",", ":"),
    ).encode()

    headers = signed_webhook_headers(
        raw_body,
        event_id="evt_004",
    )

    with TestClient(app) as client:
        first = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers=headers,
        )

        second = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.json()["transaction_state"] == (
        "SUCCESS"
    )
    assert second.json()["transaction_state"] == (
        "SUCCESS"
    )

    stored = event_store.get("evt_004")

    assert stored is not None
    assert stored.status.value == "PROCESSED"


def test_webhook_endpoint_returns_conflict_for_unknown_transaction(
    tmp_path,
):
    event_store = WebhookEventStore(
        str(tmp_path / "webhooks.db")
    )

    transaction_store = SQLiteTransactionStore(
        str(tmp_path / "transactions.db")
    )

    engine = ReconciliationEngine(
        webhook_store=event_store,
        transaction_store=transaction_store,
    )

    app = build_webhook_client(engine)

    raw_body = json.dumps(
        webhook_payload(),
        separators=(",", ":"),
    ).encode()

    headers = signed_webhook_headers(
        raw_body,
        event_id="evt_005",
    )

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers=headers,
        )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "No transaction found for webhook event"
    )

    assert event_store.get("evt_005") is None
def test_execute_requires_authentication():
    app, _, _, _ = build_client()

    app.dependency_overrides.pop(
        get_authenticated_principal,
        None,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={
                "Idempotency-Key": "exec_001",
            },
            json={
                "user_message": "Buy groceries under ₹2000.",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Authentication required"
    )
def build_authenticated_client():
    app = create_app()

    orchestrator = FakeOrchestrator()
    transaction_store = FakeTransactionStore()
    audit_trail = FakeAuditTrail()

    app.dependency_overrides[get_orchestrator] = (
        lambda: orchestrator
    )
    app.dependency_overrides[get_transaction_store] = (
        lambda: transaction_store
    )
    app.dependency_overrides[get_audit_trail] = (
        lambda: audit_trail
    )

    app.state.api_token = (
        "12345678901234567890123456789012"
    )
    app.state.api_user_id = "user_123"
    app.state.api_agent_id = "agent_001"

    return app
def test_execute_accepts_valid_bearer_token():
    app = build_authenticated_client()

    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={
                "Authorization": (
                    "Bearer "
                    "12345678901234567890123456789012"
                ),
                "Idempotency-Key": "exec_001",
            },
            json={
                "user_message": "Buy groceries.",
            },
        )

    assert response.status_code == 200

def test_execute_rejects_invalid_bearer_token():
    app = build_authenticated_client()

    with TestClient(app) as client:
        response = client.post(
            "/v1/agent/execute",
            headers={
                "Authorization": "Bearer wrong-token",
                "Idempotency-Key": "exec_001",
            },
            json={
                "user_message": "Buy groceries.",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Invalid authentication credentials"
    )

def test_transaction_endpoint_denies_cross_owner_access():
    now = datetime.now(timezone.utc)

    transaction = TransactionRecord(
        transaction_id="txn_other",
        intent_id="intent_other",
        user_id="user_456",
        agent_id="agent_999",
        merchant_id="merchant_001",
        amount_paise=450000,
        currency="INR",
        items=[
            IntentItem(
                sku="shoe_001",
                quantity=1,
            )
        ],
        authorization_snapshot=None,
        intent_hash="a" * 64,
        idempotency_key="exec_other",
        state=TransactionState.DISPATCHED,
        razorpay_order_id="order_other",
        razorpay_payment_id=None,
        created_at=now,
        updated_at=now,
    )

    app = create_app()

    app.dependency_overrides[get_transaction_store] = (
        lambda: FakeTransactionStore(transaction)
    )
    app.dependency_overrides[get_authenticated_principal] = (
        lambda: AuthenticatedPrincipal(
            user_id="user_123",
            agent_id="agent_001",
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/v1/transactions/txn_other"
        )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Transaction access denied"
    )


def test_transaction_audit_endpoint_denies_cross_owner_access():
    now = datetime.now(timezone.utc)

    transaction = TransactionRecord(
        transaction_id="txn_other",
        intent_id="intent_other",
        user_id="user_456",
        agent_id="agent_999",
        merchant_id="merchant_001",
        amount_paise=450000,
        currency="INR",
        items=[
            IntentItem(
                sku="shoe_001",
                quantity=1,
            )
        ],
        authorization_snapshot=None,
        intent_hash="a" * 64,
        idempotency_key="exec_other",
        state=TransactionState.DISPATCHED,
        razorpay_order_id="order_other",
        razorpay_payment_id=None,
        created_at=now,
        updated_at=now,
    )

    app = create_app()

    app.dependency_overrides[get_transaction_store] = (
        lambda: FakeTransactionStore(transaction)
    )
    app.dependency_overrides[get_audit_trail] = (
        lambda: FakeAuditTrail()
    )
    app.dependency_overrides[get_authenticated_principal] = (
        lambda: AuthenticatedPrincipal(
            user_id="user_123",
            agent_id="agent_001",
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/v1/transactions/txn_other/audit"
        )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Transaction access denied"
    )


