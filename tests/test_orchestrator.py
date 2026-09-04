from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from application.orchestrator import (
    AgentShieldOrchestrator,
    OrchestrationError,
)
from engine.idempotency import WALIdempotencyStore
from models.policy import PolicyDecision, TransactionPolicy
from engine.catalog import SQLiteCatalog
from models.catalog import CatalogProduct
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
from models.authorization import (
    AgentAuthorization,
    AuthorizationDecision,
    AuthorizationEvaluation,
)
from models.mandate import Mandate
from models.orchestration import OrchestrationResult
from models.policy import TransactionPolicy
from models.transaction import TransactionState
from models.transaction import (
    IdempotencyStatus,
    TransactionState,
)


# Fixtures / factories


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


def make_server_authorization() -> AgentAuthorization:
    return AgentAuthorization(
        user_id="user_123",
        agent_id="agent_001",
        authorization_id="auth_001",
        active=True,
        revoked=False,
        max_amount_paise=500000,
        allowed_merchants=["merchant_001"],
        allowed_categories=["footwear"],
        allowed_skus=["shoe_001"],
        max_quantity=2,
        currency="INR",
    )


def approved_authorization() -> AuthorizationEvaluation:
    authorization = make_server_authorization()

    return AuthorizationEvaluation(
        decision=AuthorizationDecision(
            allowed=True,
            reason="AUTHORIZATION_APPROVED",
            authorization_id=authorization.authorization_id,
        ),
        authorization=authorization,
    )


def rejected_authorization() -> AuthorizationEvaluation:
    authorization = make_server_authorization()

    return AuthorizationEvaluation(
        decision=AuthorizationDecision(
            allowed=False,
            reason="AUTHORIZATION_REJECTED",
            authorization_id=authorization.authorization_id,
        ),
        authorization=authorization,
    )

def make_orchestrator(
    tmp_path: Path,
    *,
    claude=None,
    razorpay=None,
    authorization_check=None,
    policy_provider=None,
    mandate_engine=None,
    policy_engine=None,
):
    claude = claude if claude is not None else FakeClaude()
    razorpay = razorpay if razorpay is not None else FakeRazorpay()

    audit_trail = SQLiteAuditTrail(
        str(tmp_path / "audit.db")
    )
    transaction_store = SQLiteTransactionStore(
        tmp_path / "transactions.db"
    )

    catalog = SQLiteCatalog(
        str(tmp_path / "catalog.db")
    )
    catalog.create(
        CatalogProduct(
            merchant_id="merchant_001",
            sku="shoe_001",
            name="Running Shoes",
            category="footwear",
            price_paise=450000,
            currency="INR",
            stock=20,
        )
    )

    if authorization_check is None:
        def authorization_check(_analysis):
            return approved_authorization()

    if policy_provider is None:
        policy_provider = FakePolicyProvider()

    if mandate_engine is None:
        mandate_engine = AP2AlignedMandateEngine(
            b"test-secret-key"
        )

    orchestrator = AgentShieldOrchestrator(
        claude=claude,
        authorization_check=authorization_check,
        policy_engine=(
            policy_engine
            if policy_engine is not None
            else DeterministicPolicyEngine()
        ),
        catalog=catalog,
        intent_hasher=IntentHasher(),
        mandate_engine=mandate_engine,
        idempotency_store=WALIdempotencyStore(
            tmp_path / "state.db"
        ),
        razorpay=razorpay,
        policy_provider=policy_provider,
        audit_trail=audit_trail,
        transaction_store=transaction_store,
    )

    return (
        orchestrator,
        claude,
        razorpay,
        audit_trail,
        transaction_store,
        catalog,
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
        catalog,
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
    orchestrator, _, _, _audit_trail, _transaction_store, _ = make_orchestrator(
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
    assert stored.authorization_snapshot is not None
    assert stored.authorization_snapshot.authorization_id == "auth_001"



# Authorization


@pytest.mark.asyncio
async def test_authorization_failure_blocks_before_razorpay(
    tmp_path: Path,
):
    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
        tmp_path,
        authorization_check=lambda _analysis: rejected_authorization(),
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

@pytest.mark.asyncio
async def test_authorization_rejection_skips_policy_evaluation(
    tmp_path: Path,
):
    class FailingPolicyEngine:
        def __init__(self):
            self.called = False

        def evaluate(
            self,
            *args,
            **kwargs,
        ):
            self.called = True
            raise AssertionError(
                "policy evaluation must not run after "
                "authorization rejection"
            )

    policy_engine = FailingPolicyEngine()

    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
        tmp_path,
        authorization_check=lambda _analysis: rejected_authorization(),
        policy_engine=policy_engine,
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

    assert policy_engine.called is False
    assert razorpay.called is False

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert events[-1].event_type == (
        AuditEventType.AUTHORIZATION_REJECTED
    )

@pytest.mark.asyncio
async def test_orchestrator_passes_catalog_to_policy_engine(
    tmp_path: Path,
):
    class CatalogCapturingPolicyEngine:
        def __init__(self):
            self.catalog = None

        def evaluate(
            self,
            proposal,
            authorization,
            policy,
            *,
            catalog=None,
        ):
            self.catalog = catalog

            return PolicyDecision(
                allowed=True,
                reason="POLICY_APPROVED",
                details={},
            )

    policy_engine = CatalogCapturingPolicyEngine()

    orchestrator, _, _, _, _, expected_catalog = make_orchestrator(
        tmp_path,
        policy_engine=policy_engine,
    )

    await orchestrator.execute(
        user_message="Buy running shoes under ₹5000.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        transaction_id="txn_001",
        idempotency_key="exec_001",
    )

    assert policy_engine.catalog is expected_catalog

# Idempotency


@pytest.mark.asyncio
async def test_duplicate_execution_is_blocked_before_razorpay(
    tmp_path: Path,
):
    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
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
                            update={"user_id": "attacker"}
                        )
                    )
                }
            )

    orchestrator, _, razorpay, _, _, _ = make_orchestrator(
        tmp_path,
        claude=MaliciousClaude(),
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

    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
        tmp_path,
        policy_provider=restrictive_policy,
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
    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
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

    orchestrator, _, razorpay, _, _, _ = make_orchestrator(
        tmp_path,
        mandate_engine=InvalidMandateEngine(),
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

@pytest.mark.asyncio
async def test_unexpected_razorpay_error_persists_unknown_state(
    tmp_path: Path,
):
    class UnexpectedFailureRazorpay:
        async def create_order(
            self,
            *,
            amount_paise,
            currency,
            receipt,
            notes,
        ):
            raise RuntimeError("unexpected upstream failure")

    (
        orchestrator,
        _,
        _,
        audit_trail,
        transaction_store,
        _,
    ) = make_orchestrator(
        tmp_path,
        razorpay=UnexpectedFailureRazorpay(),
    )

    with pytest.raises(
        OrchestrationError,
        match="unknown after dispatch failure",
    ):
        await orchestrator.execute(
            user_message="Buy running shoes under ₹5000.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
            transaction_id="txn_001",
            idempotency_key="exec_001",
        )

    stored = transaction_store.get("txn_001")

    assert stored is not None
    assert stored.state == TransactionState.UNKNOWN

    idempotency_store = WALIdempotencyStore(
        tmp_path / "state.db"
    )

    idempotency_record = idempotency_store.get(
        "exec_001"
    )

    assert idempotency_record is not None
    assert idempotency_record.status == IdempotencyStatus.ACQUIRED

    events = audit_trail.list_events(
        transaction_id="txn_001"
    )

    assert events[-1].event_type == (
        AuditEventType.RAZORPAY_UNKNOWN
    )

    assert events[-1].details == {
        "reason": "external_execution_error",
        "error_type": "RuntimeError",
    }

    assert audit_trail.verify_chain() is True

# Authorization result contract


@pytest.mark.asyncio
async def test_invalid_authorization_result_is_rejected(
    tmp_path: Path,
):
    orchestrator, _, razorpay, _, _, _ = make_orchestrator(
        tmp_path,
        authorization_check=lambda _analysis: "invalid",
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

@pytest.mark.asyncio
async def test_revoked_authorization_blocks_execution(
    tmp_path: Path,
):
    authorization = make_server_authorization()
    revoked = authorization.model_copy(
        update={
            "active": False,
            "revoked": True,
        }
    )

    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
        tmp_path,
        authorization_check=lambda _analysis: AuthorizationEvaluation(
            decision=AuthorizationDecision(
                allowed=False,
                reason="AUTHORIZATION_REVOKED",
                authorization_id=revoked.authorization_id,
            ),
            authorization=revoked,
        ),
    )

    with pytest.raises(
        OrchestrationError,
        match="authorization rejected: AUTHORIZATION_REVOKED",
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
        AuditEventType.AUTHORIZATION_REJECTED
    )

    assert events[-1].details == {
        "authorization_id": "auth_001",
        "reason": "AUTHORIZATION_REVOKED",
    }

    assert audit_trail.verify_chain() is True

@pytest.mark.asyncio
async def test_changed_authorization_bounds_block_old_execution_path(
    tmp_path: Path,
):
    original = make_server_authorization()

    changed = original.model_copy(
        update={
            "max_amount_paise": 400000,
        }
    )

    orchestrator, _, razorpay, audit_trail, _, _ = make_orchestrator(
        tmp_path,
        authorization_check=lambda _analysis: AuthorizationEvaluation(
            decision=AuthorizationDecision(
                allowed=False,
                reason="AMOUNT_EXCEEDS_AUTHORIZATION_LIMIT",
                authorization_id=changed.authorization_id,
            ),
            authorization=changed,
        ),
    )

    with pytest.raises(
        OrchestrationError,
        match=(
            "authorization rejected: "
            "AMOUNT_EXCEEDS_AUTHORIZATION_LIMIT"
        ),
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
        AuditEventType.AUTHORIZATION_REJECTED
    )

    assert events[-1].details == {
        "authorization_id": "auth_001",
        "reason": "AMOUNT_EXCEEDS_AUTHORIZATION_LIMIT",
    }

    assert audit_trail.verify_chain() is True
