from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from application.orchestrator import AgentShieldOrchestrator, OrchestrationError
from engine.audit import SQLiteAuditTrail
from engine.transaction_store import SQLiteTransactionStore
from models.audit import AuditEvent
from models.orchestration import OrchestrationResult
from models.transaction import TransactionRecord

from .dependencies import (
    get_audit_trail,
    get_orchestrator,
    get_transaction_store,
)


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )


class AgentExecuteRequest(StrictRequestModel):
    user_message: StrictStr = Field(min_length=1)
    user_id: StrictStr = Field(min_length=1)
    agent_id: StrictStr = Field(min_length=1)
    merchant_context: dict[str, object] | None = None

    @field_validator("user_message", "user_id", "agent_id")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value


class HealthResponse(StrictRequestModel):
    status: StrictStr


class AgentShieldAPI:
    """Thin HTTP transport for the AgentShield application layer."""

    def __init__(self) -> None:
        self.app = FastAPI(
            title="AgentShield APEX",
            version="0.1.0",
            description=(
                "Deterministic governance/control plane for AI-initiated "
                "financial actions."
            ),
        )
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.get(
            "/healthz",
            response_model=HealthResponse,
            status_code=status.HTTP_200_OK,
        )
        async def healthz() -> HealthResponse:
            return HealthResponse(status="ok")

        @self.app.post(
            "/v1/agent/execute",
            response_model=OrchestrationResult,
            status_code=status.HTTP_200_OK,
        )
        async def execute_agent(
            payload: AgentExecuteRequest,
            idempotency_key: str = Header(
                alias="Idempotency-Key",
                min_length=1,
            ),
            orchestrator: AgentShieldOrchestrator = Depends(
                get_orchestrator
            ),
        ) -> OrchestrationResult:
            if not idempotency_key.strip():
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key cannot be blank",
                )

            intent_id = f"intent_{uuid4().hex}"
            transaction_id = f"txn_{uuid4().hex}"

            try:
                return await orchestrator.execute(
                    user_message=payload.user_message,
                    user_id=payload.user_id,
                    agent_id=payload.agent_id,
                    intent_id=intent_id,
                    transaction_id=transaction_id,
                    idempotency_key=idempotency_key,
                    merchant_context=payload.merchant_context,
                )
            except OrchestrationError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=str(exc),
                ) from exc

        @self.app.get(
            "/v1/transactions/{transaction_id}",
            response_model=TransactionRecord,
            status_code=status.HTTP_200_OK,
        )
        async def get_transaction(
            transaction_id: str = Path(min_length=1),
            transaction_store: SQLiteTransactionStore = Depends(
                get_transaction_store
            ),
        ) -> TransactionRecord:
            transaction = transaction_store.get(transaction_id)
            if transaction is None:
                raise HTTPException(
                    status_code=404,
                    detail="Transaction not found",
                )
            return transaction

        @self.app.get(
            "/v1/transactions/{transaction_id}/audit",
            response_model=list[AuditEvent],
            status_code=status.HTTP_200_OK,
        )
        async def get_transaction_audit(
            transaction_id: str = Path(min_length=1),
            audit_trail: SQLiteAuditTrail = Depends(get_audit_trail),
        ) -> list[AuditEvent]:
            return audit_trail.list_events(transaction_id=transaction_id)


def create_app() -> FastAPI:
    return AgentShieldAPI().app


app = create_app()
