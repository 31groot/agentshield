from __future__ import annotations

from fastapi import HTTPException, Request

from application.orchestrator import AgentShieldOrchestrator
from engine.audit import SQLiteAuditTrail
from engine.transaction_store import SQLiteTransactionStore


def configure_app(
    request: Request,
    *,
    orchestrator: AgentShieldOrchestrator,
    transaction_store: SQLiteTransactionStore,
    audit_trail: SQLiteAuditTrail,
) -> None:
    """
    Attach application-scoped governance dependencies.

    The API layer owns dependency wiring only. Business authorization,
    policy, mandate, state-machine, idempotency, and Razorpay decisions stay
    inside the application/domain layers.
    """
    request.app.state.orchestrator = orchestrator
    request.app.state.transaction_store = transaction_store
    request.app.state.audit_trail = audit_trail


def get_orchestrator(request: Request) -> AgentShieldOrchestrator:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="AgentShield orchestrator is not configured",
        )
    return orchestrator


def get_transaction_store(request: Request) -> SQLiteTransactionStore:
    store = getattr(request.app.state, "transaction_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Transaction store is not configured",
        )
    return store


def get_audit_trail(request: Request) -> SQLiteAuditTrail:
    audit_trail = getattr(request.app.state, "audit_trail", None)
    if audit_trail is None:
        raise HTTPException(
            status_code=503,
            detail="Audit trail is not configured",
        )
    return audit_trail
