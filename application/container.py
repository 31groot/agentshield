from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import anthropic

from application.orchestrator import AgentShieldOrchestrator
from config import Settings
from engine.audit import SQLiteAuditTrail
from engine.hashing import IntentHasher
from engine.idempotency import WALIdempotencyStore
from engine.mandate import AP2AlignedMandateEngine
from engine.policy import DeterministicPolicyEngine
from engine.transaction_store import SQLiteTransactionStore
from integrations.claude import ClaudeIntentParser
from integrations.razorpay import RazorpayClient
from models.authorization import AuthorizationDecision
from models.intent import AgentRequestAnalysis
from models.policy import TransactionPolicy


class FailClosedAuthorizationProvider:
    """
    Temporary fail-closed authorization provider.

    Until the real server-owned AuthorizationAuthority is implemented,
    no financial action may be authorized.
    """

    def __call__(
        self,
        analysis: AgentRequestAnalysis,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=False,
            reason="AUTHORIZATION_AUTHORITY_NOT_CONFIGURED",
            authorization_id="unconfigured",
        )


class UnconfiguredPolicyProvider:
    """
    Temporary fail-closed policy provider.

    The real server-owned policy provider will be introduced in a later
    milestone.
    """

    def __call__(
        self,
        analysis: AgentRequestAnalysis,
    ) -> TransactionPolicy:
        raise RuntimeError(
            "Server-owned policy provider is not configured"
        )


@dataclass(frozen=True)
class ApplicationContainer:
    settings: Settings
    orchestrator: AgentShieldOrchestrator
    transaction_store: SQLiteTransactionStore
    audit_trail: SQLiteAuditTrail
    razorpay: RazorpayClient

    @classmethod
    def from_environment(
        cls,
        *,
        settings: Settings | None = None,
        authorization_check: Callable[
            [AgentRequestAnalysis],
            AuthorizationDecision,
        ] | None = None,
        policy_provider: Callable[
            [AgentRequestAnalysis],
            TransactionPolicy,
        ] | None = None,
    ) -> "ApplicationContainer":
        """
        Build the application dependency graph.

        Production callers load Settings from the environment.
        Tests may inject Settings and governance providers so that
        construction can be verified without making live API calls.
        """

        resolved_settings = (
            settings
            if settings is not None
            else Settings.from_environment()
        )

        resolved_authorization_check = (
            authorization_check
            if authorization_check is not None
            else FailClosedAuthorizationProvider()
        )

        resolved_policy_provider = (
            policy_provider
            if policy_provider is not None
            else UnconfiguredPolicyProvider()
        )

        mandate_secret_key = resolved_settings.mandate_secret_key

        if isinstance(mandate_secret_key, str):
            mandate_secret_key = mandate_secret_key.encode("utf-8")

        anthropic_client = anthropic.Anthropic(
            api_key=resolved_settings.anthropic_api_key,
        )

        claude = ClaudeIntentParser(
            client=anthropic_client,
            model=resolved_settings.claude_model,
        )

        razorpay = RazorpayClient(
            key_id=resolved_settings.razorpay_key_id,
            key_secret=resolved_settings.razorpay_key_secret,
            timeout_seconds=resolved_settings.request_timeout_seconds,
        )

        transaction_store = SQLiteTransactionStore(
            f"{resolved_settings.database_path}.transactions",
        )

        audit_trail = SQLiteAuditTrail(
            f"{resolved_settings.database_path}.audit",
        )

        idempotency_store = WALIdempotencyStore(
            f"{resolved_settings.database_path}.idempotency",
        )

        intent_hasher = IntentHasher()

        mandate_engine = AP2AlignedMandateEngine(
            mandate_secret_key,
            hasher=intent_hasher,
        )

        policy_engine = DeterministicPolicyEngine()

        orchestrator = AgentShieldOrchestrator(
            claude=claude,
            authorization_check=resolved_authorization_check,
            policy_engine=policy_engine,
            intent_hasher=intent_hasher,
            mandate_engine=mandate_engine,
            idempotency_store=idempotency_store,
            razorpay=razorpay,
            policy_provider=resolved_policy_provider,
            audit_trail=audit_trail,
            transaction_store=transaction_store,
        )

        return cls(
            settings=resolved_settings,
            orchestrator=orchestrator,
            transaction_store=transaction_store,
            audit_trail=audit_trail,
            razorpay=razorpay,
        )