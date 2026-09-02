from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from engine.hashing import IntentHasher
from engine.idempotency import WALIdempotencyStore
from engine.mandate import AP2AlignedMandateEngine
from engine.policy import DeterministicPolicyEngine
from engine.state_machine import (
    InvalidTransactionTransition,
    TransactionStateMachine,
)
from integrations.claude import ClaudeIntentParser
from integrations.razorpay import (
    RazorpayClient,
    RazorpayNetworkError,
)
from models.intent import AgentRequestAnalysis
from models.mandate import Mandate
from models.policy import (
    PolicyDecision,
    TransactionPolicy,
)
from models.authorization import  AuthorizationDecision

from models.transaction import (
    TransactionRecord,
    TransactionState,
)
from models.orchestration import OrchestrationResult


class OrchestrationError(Exception):
    """
    Raised when the AgentShield workflow cannot safely continue.
    """


class AgentShieldOrchestrator:
    """
    Application-level coordinator for AgentShield.

    The orchestrator controls the order in which the security
    and execution layers are applied.

    Only a fully governed transaction can reach Razorpay.
    """

    def __init__(
        self,
        *,
        claude: ClaudeIntentParser,
        authorization_check: Callable[
            [AgentRequestAnalysis],
            AuthorizationDecision,
        ],
        policy_engine: DeterministicPolicyEngine,
        intent_hasher: IntentHasher,
        mandate_engine: AP2AlignedMandateEngine,
        idempotency_store: WALIdempotencyStore,
        razorpay: RazorpayClient,
        state_machine: type[
            TransactionStateMachine
        ] = TransactionStateMachine,
        policy_provider: Callable[
            [AgentRequestAnalysis],
            TransactionPolicy,
        ],
    ) -> None:
        self._claude = claude
        self._authorization_check = authorization_check
        self._policy_engine = policy_engine
        self._intent_hasher = intent_hasher
        self._mandate_engine = mandate_engine
        self._idempotency_store = idempotency_store
        self._razorpay = razorpay
        self._state_machine = state_machine
        self._policy_provider = policy_provider

    async def execute(
        self,
        *,
        user_message: str,
        user_id: str,
        agent_id: str,
        intent_id: str,
        transaction_id: str,
        idempotency_key: str,
        merchant_context: dict[str, Any] | None = None,
    ) -> OrchestrationResult:
        """
        Execute one complete AgentShield governance flow.

        Workflow:

            Claude
              ↓
            Intent validation
              ↓
            Authorization
              ↓
            Hash
              ↓
            Mandate creation + verification
              ↓
            MANDATE_VALID
              ↓
            Policy
              ↓
            POLICY_APPROVED
              ↓
            Idempotency
              ↓
            LOCK_ACQUIRED
              ↓
            Razorpay order
              ↓
            DISPATCHED

        Razorpay is never called before the required
        AgentShield governance checks succeed.
        """

        # =========================================================
        # 0. Validate server-owned execution identifiers
        # =========================================================

        self._require_non_empty(
            user_id,
            "user_id",
        )

        self._require_non_empty(
            agent_id,
            "agent_id",
        )

        self._require_non_empty(
            intent_id,
            "intent_id",
        )

        self._require_non_empty(
            transaction_id,
            "transaction_id",
        )

        self._require_non_empty(
            idempotency_key,
            "idempotency_key",
        )

        # =========================================================
        # 1. Claude / intent interpretation
        # =========================================================

        analysis = self._claude.parse(
            user_message,
            user_id=user_id,
            agent_id=agent_id,
            intent_id=intent_id,
            merchant_context=merchant_context,
        )

        self._assert_identity_binding(
            analysis=analysis,
            user_id=user_id,
            agent_id=agent_id,
            intent_id=intent_id,
        )

        proposal = analysis.intent_proposal
        authorization = analysis.authorization

        # =========================================================
        # 2. Create initial server-owned transaction
        # =========================================================

        transaction = TransactionRecord(
            transaction_id=transaction_id,
            intent_id=intent_id,
            user_id=user_id,
            agent_id=agent_id,
            merchant_id=proposal.merchant_id,
            amount_paise=proposal.amount_paise,
            currency=proposal.currency,
            items=proposal.items,
            intent_hash="0" * 64,
            idempotency_key=idempotency_key,
            state=TransactionState.CREATED,
        )

        # =========================================================
        # 3. CREATED → INTENT_VALIDATED
        # =========================================================

        transaction = self._transition(
            transaction,
            TransactionState.INTENT_VALIDATED,
        )

        # =========================================================
        # 4. Authorization
        # =========================================================

        authorization_result = self._authorization_check(
            analysis
        )

        if not isinstance(
            authorization_result,
            AuthorizationDecision,
        ):
            raise OrchestrationError(
                "Authorization check returned an invalid result"
            )

        if not authorization_result.allowed:
            raise OrchestrationError(
                "AgentShield authorization rejected the request: "
                f"{authorization_result.reason}"
            )

        # =========================================================
        # 7. Policy
        # =========================================================

        policy = self._policy_provider(
            analysis
        )

        policy_result: PolicyDecision = (
            self._policy_engine.evaluate(
                proposal,
                authorization,
                policy,
            )
        )

        if not policy_result.allowed:
            raise OrchestrationError(
                "Policy rejected transaction: "
                f"{policy_result.reason}"
            )

        transaction = self._transition(
            transaction,
            TransactionState.POLICY_APPROVED,
        )


        # =========================================================
        # 5. Hash governed intent
        # =========================================================

        intent_hash = self._intent_hasher.hash(
            authorization,
            proposal,
        )

        transaction = transaction.model_copy(
            update={
                "intent_hash": intent_hash,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        # =========================================================
        # 6. Create and verify mandate
        # =========================================================

        mandate = self._mandate_engine.create(
            authorization=authorization,
            proposal=proposal,
        )

        mandate_valid = self._mandate_engine.verify(
            mandate=mandate,
            authorization=authorization,
            proposal=proposal,
        )

        if not mandate_valid:
            raise OrchestrationError(
                "Mandate verification failed"
            )

        transaction = self._transition(
            transaction,
            TransactionState.MANDATE_VALID,
        )

        # =========================================================
        # 8. Idempotency / execution lock
        # =========================================================

        acquired = self._idempotency_store.acquire(
            idempotency_key=idempotency_key,
            transaction_id=transaction_id,
        )

        if not acquired:
            raise OrchestrationError(
                "Execution already claimed for idempotency key"
            )

        transaction = self._transition(
            transaction,
            TransactionState.LOCK_ACQUIRED,
        )

        # =========================================================
        # 9. Dispatch to Razorpay
        # =========================================================

        try:
            order = await self._razorpay.create_order(
                amount_paise=transaction.amount_paise,
                currency=transaction.currency,
                receipt=transaction.transaction_id,
                notes={
                    "transaction_id": transaction.transaction_id,
                    "intent_id": transaction.intent_id,
                    "intent_hash": transaction.intent_hash,
                },
            )

        except RazorpayNetworkError as exc:
            """
            We cannot determine whether Razorpay received the
            request, so the transaction enters UNKNOWN.

            Recovery must reconcile the external payment state
            before any retry is considered.
            """

            transaction = self._transition(
                transaction,
                TransactionState.DISPATCHED,
            )

            transaction = self._transition(
                transaction,
                TransactionState.UNKNOWN,
            )

            raise OrchestrationError(
                "Razorpay outcome is unknown after network failure"
            ) from exc

        # =========================================================
        # 10. Verify Razorpay order response
        # =========================================================

        if order.amount_paise != transaction.amount_paise:
            raise OrchestrationError(
                "Razorpay order amount does not match "
                "the governed transaction"
            )

        if order.currency != transaction.currency:
            raise OrchestrationError(
                "Razorpay order currency does not match "
                "the governed transaction"
            )

        # =========================================================
        # 11. Record Razorpay order
        # =========================================================

        transaction = transaction.model_copy(
            update={
                "razorpay_order_id": order.order_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        # =========================================================
        # 12. LOCK_ACQUIRED → DISPATCHED
        # =========================================================

        transaction = self._transition(
            transaction,
            TransactionState.DISPATCHED,
        )

        return OrchestrationResult(
            transaction=transaction,
            mandate=mandate,
            status="DISPATCHED",
        )

    def _transition(
        self,
        transaction: TransactionRecord,
        target: TransactionState,
    ) -> TransactionRecord:
        """
        Apply exactly one legal state transition through
        the configured transaction state machine.
        """

        try:
            next_state = self._state_machine.transition(
                transaction.state,
                target,
            )
        except InvalidTransactionTransition as exc:
            raise OrchestrationError(
                "Invalid orchestration state transition: "
                f"{transaction.state.value} -> {target.value}"
            ) from exc

        return transaction.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    @staticmethod
    def _assert_identity_binding(
        *,
        analysis: AgentRequestAnalysis,
        user_id: str,
        agent_id: str,
        intent_id: str,
    ) -> None:
        """
        Ensure Claude output cannot override server-owned identity.
        """

        proposal = analysis.intent_proposal

        if proposal.user_id != user_id:
            raise OrchestrationError(
                "Claude analysis contains unexpected user_id"
            )

        if proposal.agent_id != agent_id:
            raise OrchestrationError(
                "Claude analysis contains unexpected agent_id"
            )

        if proposal.intent_id != intent_id:
            raise OrchestrationError(
                "Claude analysis contains unexpected intent_id"
            )

        if analysis.raw_user_prompt != proposal.raw_user_prompt:
            raise OrchestrationError(
                "Claude analysis contains inconsistent raw user prompts"
            )

        if not analysis.raw_user_prompt.strip():
            raise OrchestrationError(
                "Claude analysis contains an empty raw prompt"
            )

    @staticmethod
    def _require_non_empty(
        value: str,
        field_name: str,
    ) -> None:
        if not value.strip():
            raise ValueError(
                f"{field_name} cannot be empty"
            )