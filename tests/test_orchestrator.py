from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from application.orchestrator import (
    AgentShieldOrchestrator,
    OrchestrationError,
)

from models.audit import AuditEventType
from engine.audit import SQLiteAuditTrail
from engine.transaction_store import SQLiteTransactionStore
from engine.hashing import IntentHasher
from engine.idempotency import WALIdempotencyStore
from engine.mandate import AP2AlignedMandateEngine
from engine.policy import DeterministicPolicyEngine

from models.intent import (
    AgentRequestAnalysis,
    AuthorizationInterpretation,
    IntentItem,
    IntentProposal,
)

from models.mandate import Mandate

from models.orchestration import OrchestrationResult

from models.policy import TransactionPolicy
from models.authorization import AuthorizationDecision

from models.transaction import TransactionState


# =========================================================
# Fixtures / factories
# =========================================================


def make_analysis() -> AgentRequestAnalysis:
    now = datetime.now(timezone.utc)

    authorization = AuthorizationInterpretation(
        max_amount_paise=500000,
        currency="INR",
        product_constraints=["running shoes"],
        allowed_merchants=[],
        max_quantity=1,
        constraints=[
            "running shoes",
            "maximum ₹5000",
        ],
    )

    proposal = IntentProposal(
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        raw_user_prompt="Buy running shoes under ₹5000.",
        merchant_id="merchant_001",
        amount_paise=450000,
        currency="INR",
        items=[
            IntentItem(
                sku="shoe_001",
                quantity=1,
            )
        ],
        action_type="CREATE_ORDER",
        nonce="nonce_001",
        created_at=now,
        ttl_seconds=300,
    )

    return AgentRequestAnalysis(
        raw_user_prompt="Buy running shoes under ₹5000.",
        authorization=authorization,
        intent_proposal=proposal,
    )


class FakeClaude:
    def __init__(self):
        self.called = False

    def parse(
        self,
        user_message,
        *,
        user_id,
        agent_id,
        intent_id,
        merchant_context=None,
    ):
        self.called = True

        return make_analysis()


class FakeRazorpayOrder:
    def __init__(self):
        self.order_id = "order_001"
        self.amount_paise = 450000
        self.currency = "INR"
        self.status = "created"


class FakeRazorpay:
    def __init__(self):
        self.called = False

    async def create_order(
        self,
        *,
        amount_paise,
        currency,
        receipt,
        notes,
    ):
        self.called = True

        assert amount_paise == 450000
        assert currency == "INR"
        assert receipt == "txn_001"

        return FakeRazorpayOrder()


class FakePolicyProvider:
    def __call__(
        self,
        analysis,
    ):
        return TransactionPolicy(
            user_id="user_123",
            agent_id="agent_001",
            max_amount_paise=500000,
            min_amount_paise=10000,
            allowed_merchants=["merchant_001"],
            allowed_categories=[],
            allowed_skus=["shoe_001"],
            max_quantity=2,
            currency="INR",
            bank_rail_available=True,
        )


def approved_authorization() -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=True,
        reason="AUTHORIZATION_APPROVED",
        authorization_id="auth_001",
    )


def rejected_authorization() -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=False,
        reason="AUTHORIZATION_REJECTED",
        authorization_id="auth_001",
    )


def make_orchestrator(
    tmp_path: Path,
):
    claude = FakeClaude()
    razorpay = FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )
    transaction_store = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )

    def authorization_check(
        analysis,
    ):
        return approved_authorization()

    orchestrator = AgentShieldOrchestrator(
        claude=claude,
        authorization_check=authorization_check,
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=AP2AlignedMandateEngine(
            b"test-secret-key"
        ),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=FakePolicyProvider(),
        audit_trail=audit_trail,
        transaction_store=transaction_store,
    )

    return (
        orchestrator,
        claude,
        razorpay,
        audit_trail,
        transaction_store,
    )



# Happy path


@pytest.mark.asyncio
async def test_execute_runs_full_happy_path(
    tmp_path: Path,
):
    (
        orchestrator,
        claude,
        razorpay,
        audit_trail,
        transaction_store,
    ) = make_orchestrator(tmp_path)

    result = await orchestrator.execute(
        user_message="Buy running shoes under ₹5000.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        transaction_id="txn_001",
        idempotency_key="exec_001",
    )

    assert isinstance(
        result,
        OrchestrationResult,
    )
    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.INTENT_RECEIVED,
        AuditEventType.INTENT_VALIDATED,
        AuditEventType.AUTHORIZATION_APPROVED,
        AuditEventType.POLICY_APPROVED,
        AuditEventType.MANDATE_CREATED,
        AuditEventType.MANDATE_VERIFIED,
        AuditEventType.IDEMPOTENCY_ACQUIRED,
        AuditEventType.RAZORPAY_DISPATCHED,
    ]

    assert claude.called is True
    assert razorpay.called is True

    assert result.transaction.transaction_id == "txn_001"

    assert result.transaction.intent_id == "intent_001"

    assert (
        result.transaction.state
        == TransactionState.DISPATCHED
    )

    assert (
        result.transaction.razorpay_order_id
        == "order_001"
    )

    assert len(
        result.transaction.intent_hash
    ) == 64

    assert isinstance(
        result.mandate,
        Mandate,
    )

    assert result.mandate.signature

    assert result.status == "DISPATCHED"

    stored = transaction_store.get("txn_001")
    assert stored is not None
    assert stored.state == TransactionState.DISPATCHED
    assert stored.razorpay_order_id == "order_001"
    assert stored.intent_hash == result.transaction.intent_hash

    assert audit_trail.verify_chain() is True


@pytest.mark.asyncio
async def test_transaction_store_persists_across_store_instances(
    tmp_path: Path,
):
    orchestrator, _, _, _audit_trail, _transaction_store = make_orchestrator(
        tmp_path
    )

    await orchestrator.execute(
        user_message="Buy running shoes under ₹5000.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        transaction_id="txn_001",
        idempotency_key="exec_001",
    )

    reloaded_store = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )
    stored = reloaded_store.get("txn_001")

    assert stored is not None
    assert stored.state == TransactionState.DISPATCHED
    assert stored.razorpay_order_id == "order_001"
    assert stored.idempotency_key == "exec_001"



# Authorization


@pytest.mark.asyncio
async def test_authorization_failure_blocks_before_razorpay(
    tmp_path: Path,
):
    claude = FakeClaude()
    razorpay = FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    def authorization_check(
        analysis,
    ):
        return rejected_authorization()

    orchestrator = AgentShieldOrchestrator(
        claude=claude,
        authorization_check=authorization_check,
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=AP2AlignedMandateEngine(
            b"test-secret-key"
        ),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=FakePolicyProvider(),
        audit_trail=audit_trail,
        transaction_store=SQLiteTransactionStore(
            tmp_path / "transactions.db"
        ),
    )

    with pytest.raises(
        OrchestrationError,
        match="authorization rejected",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    assert razorpay.called is False


    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.INTENT_RECEIVED,
        AuditEventType.INTENT_VALIDATED,
        AuditEventType.AUTHORIZATION_REJECTED,
    ]

    assert events[-1].details == {
        "authorization_id": "auth_001",
        "reason": "AUTHORIZATION_REJECTED",
    }

    assert audit_trail.verify_chain() is True


# Idempotency


@pytest.mark.asyncio
async def test_duplicate_execution_is_blocked_before_razorpay(
    tmp_path: Path,
):
    orchestrator, _, razorpay, audit_trail, _ = make_orchestrator(
        tmp_path
    )

    await orchestrator.execute(
        user_message="Buy running shoes under ₹5000.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        transaction_id="txn_001",
        idempotency_key="exec_001",
    )

    razorpay.called = False


    with pytest.raises(
        OrchestrationError,
        match="already claimed",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    assert razorpay.called is False


    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert events[-1].event_type == (
        AuditEventType.IDEMPOTENCY_REJECTED
    )

    assert audit_trail.verify_chain() is True

# Claude identity boundary


@pytest.mark.asyncio
async def test_server_identity_cannot_be_overridden_by_claude(
    tmp_path: Path,
):
    class MaliciousClaude:
        def parse(
            self,
            user_message,
            *,
            user_id,
            agent_id,
            intent_id,
            merchant_context=None,
        ):
            analysis = make_analysis()

            return analysis.model_copy(
                update={
                    "intent_proposal": (
                        analysis.intent_proposal.model_copy(
                            update={
                                "user_id": "attacker",
                            }
                        )
                    )
                }
            )

    razorpay = FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    orchestrator = AgentShieldOrchestrator(
        claude=MaliciousClaude(),
        authorization_check=lambda analysis: (
            approved_authorization()
        ),
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=AP2AlignedMandateEngine(
            b"test-secret-key"
        ),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=FakePolicyProvider(),
        transaction_store=SQLiteTransactionStore(
            tmp_path / "transactions.db"
        ),
        audit_trail=audit_trail,
    )

    with pytest.raises(
        OrchestrationError,
        match="unexpected user_id",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    assert razorpay.called is False


# Policy


@pytest.mark.asyncio
async def test_policy_failure_blocks_razorpay(
    tmp_path: Path,
):
    claude = FakeClaude()
    razorpay = FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    def restrictive_policy(
        _analysis,
    ):
        return TransactionPolicy(
            user_id="user_123",
            agent_id="agent_001",
            max_amount_paise=400000,
            min_amount_paise=10000,
            allowed_merchants=["merchant_001"],
            allowed_categories=[],
            allowed_skus=["shoe_001"],
            max_quantity=2,
            currency="INR",
            bank_rail_available=True,
        )

    orchestrator = AgentShieldOrchestrator(
        claude=claude,
        authorization_check=lambda analysis: (
            approved_authorization()
        ),
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=AP2AlignedMandateEngine(
            b"test-secret-key"
        ),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=restrictive_policy,
        transaction_store=SQLiteTransactionStore(
            tmp_path / "transactions.db"
        ),
        audit_trail=audit_trail,
    )

    with pytest.raises(
        OrchestrationError,
        match="Policy rejected",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    assert razorpay.called is False

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert [event.event_type for event in events] == [
        AuditEventType.INTENT_RECEIVED,
        AuditEventType.INTENT_VALIDATED,
        AuditEventType.AUTHORIZATION_APPROVED,
        AuditEventType.POLICY_REJECTED,
    ]

    assert events[-1].details == {
        "reason": "AMOUNT_EXCEEDS_POLICY_LIMIT",
    }

    assert audit_trail.verify_chain() is True


# Server identifier validation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "   "),
        ("agent_id", "   "),
        ("intent_id", "   "),
        ("transaction_id", "   "),
        ("idempotency_key", "   "),
    ],
)
async def test_empty_server_identifier_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
):
    orchestrator, _, razorpay, _, _ = make_orchestrator(
        tmp_path
    )

    arguments = {
        "user_message": "Buy running shoes under ₹5000.",
        "user_id": "user_123",
        "agent_id": "agent_001",
        "intent_id": "intent_001",
        "transaction_id": "txn_001",
        "idempotency_key": "exec_001",
    }

    arguments[field] = value

    with pytest.raises(
        ValueError,
        match=f"{field} cannot be empty",
    ):
        await orchestrator.execute(
            **arguments,
        )

    assert razorpay.called is False


# Mandate boundary


@pytest.mark.asyncio
async def test_mandate_failure_blocks_razorpay(
    tmp_path: Path,
):
    claude = FakeClaude()
    razorpay = FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    class InvalidMandate:
        def __init__(self):
            self.expires_at = datetime.now(timezone.utc)


    class InvalidMandateEngine:
        def create(
            self,
            *,
            authorization,
            proposal,
        ):
            return InvalidMandate()

        def verify(
            self,
            *,
            mandate,
            authorization,
            proposal,
        ):
            return False

    orchestrator = AgentShieldOrchestrator(
        claude=claude,
        authorization_check=lambda analysis: (
            approved_authorization()
        ),
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=InvalidMandateEngine(),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=FakePolicyProvider(),
        transaction_store=SQLiteTransactionStore(
            tmp_path / "transactions.db"
        ),
        audit_trail=audit_trail,
    )

    with pytest.raises(
        OrchestrationError,
        match="Mandate verification failed",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    assert razorpay.called is False


# Authorization result contract


@pytest.mark.asyncio
async def test_invalid_authorization_result_is_rejected(
    tmp_path: Path,
):
    claude = FakeClaude()
    razorpay = FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )

    orchestrator = AgentShieldOrchestrator(
        claude=claude,
        authorization_check=lambda analysis: True,
        policy_engine=DeterministicPolicyEngine(),
        intent_hasher=IntentHasher(),
        mandate_engine=AP2AlignedMandateEngine(
            b"test-secret-key"
        ),
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=FakePolicyProvider(),
        transaction_store=SQLiteTransactionStore(
            tmp_path / "transactions.db"
        ),
        audit_trail=audit_trail,
    )

    with pytest.raises(
        OrchestrationError,
        match="invalid result",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    assert razorpay.called is False