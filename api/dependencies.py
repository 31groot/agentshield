from __future__ import annotations

from fastapi import HTTPException, Request

from application.orchestrator import AgentShieldOrchestrator
from engine.audit import SQLiteAuditTrail
from engine.transaction_store import SQLiteTransactionStore
from engine.reconciliation import ReconciliationEngine
from webhooks.razorpay import RazorpayWebhookHandler


def configure_app(
    request: Request,
    *,
    orchestrator: AgentShieldOrchestrator,
    transaction_store: SQLiteTransactionStore,
    audit_trail: SQLiteAuditTrail,
    webhook_handler: RazorpayWebhookHandler | None = None,
    reconciliation_engine: ReconciliationEngine | None = None,
) -> None:
    """
    Attach application-scoped governance dependencies.

    """
    request.app.state.orchestrator = orchestrator
    request.app.state.transaction_store = transaction_store
    request.app.state.audit_trail = audit_trail
    if webhook_handler is not None:
        request.app.state.webhook_handler = webhook_handler

    if reconciliation_engine is not None:
        request.app.state.reconciliation_engine = reconciliation_engine


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

def get_webhook_handler(request: Request) -> RazorpayWebhookHandler:
    handler = getattr(request.app.state, "webhook_handler", None)
    if handler is None:
        raise HTTPException(
            status_code=503,
            detail="Razorpay webhook handler is not configured",
        )
    return handler


def get_reconciliation_engine(request: Request) -> ReconciliationEngine:
    engine = getattr(request.app.state, "reconciliation_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Reconciliation engine is not configured",
        )
    return engine
