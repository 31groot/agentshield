# AgentShield APEX

**Deterministic governance and control plane for AI-initiated Razorpay payments.**

AgentShield sits between an AI agent and the payment rail. An LLM (Groq or Claude) interprets natural-language intent — but it never holds spending authority. Every decision that can move money is server-owned, deterministic code: authorization, policy limits, cryptographic mandates, idempotency, dispatch, and reconciliation all run independently of the model.

> **Core principle:** the LLM proposes, AgentShield disposes. A model can be wrong, hallucinate, or be prompt-injected — it can never authorize a payment on its own.

---

## Why this exists

Agentic commerce (an AI agent buying things on a user's behalf) has one hard requirement that most demos skip: **the model must not be the thing deciding whether money moves.** AgentShield is a reference implementation of that boundary, built around Razorpay as the payment rail and aligned with the AP2 mandate pattern used for agent-initiated transactions.

## Execution pipeline

```text
User request
    ↓
Groq / Claude intent interpretation      ← LLM boundary — advisory only
    ↓
Strict Pydantic validation
    ↓
Server-owned authentication               ← Bearer token, hmac.compare_digest
    ↓
Server-owned authorization                ← per-agent spending limits, allowlists
    ↓
Deterministic policy engine                ← amount / merchant / SKU / catalog checks
    ↓
Intent hash (SHA-256, canonicalized)
    ↓
AP2-aligned mandate (HMAC-signed, TTL-bound)
    ↓
Idempotency claim (WAL-locked)
    ↓
Razorpay order creation
    ↓
Webhook verification (HMAC signature)
    ↓
Reconciliation + hash-chained audit trail
```

Every step is enforced by a `TransactionStateMachine` that only allows explicit, one-directional transitions (including failure paths: unknown dispatch outcome → reconciliation → safe retry, or stockout → refund → reroute → recovered). A transaction cannot skip a step or resume from an invalid state.

### What the LLM is and isn't trusted with

The model interprets the request into a structured `AgentRequestAnalysis`. AgentShield then **force-overwrites** `user_id`, `agent_id`, and `intent_id` on the model's output before anything downstream sees it — so a manipulated or hallucinated LLM response can never smuggle in a different identity, and the model's "authorization interpretation" is explicitly documented as *not* an authorization decision.

## Key security properties

- **HMAC everywhere, timing-safe**: mandate signatures and Razorpay webhook signatures are verified with `hmac.compare_digest`, never `==`.
- **Signed, TTL-bound mandates**: every transaction is bound to a SHA-256 intent hash and HMAC-signed mandate that re-verifies identity, amount, nonce, and expiry before dispatch.
- **Tamper-evident audit log**: every audit event is chained (`previous_event_hash → event_hash`, SHA-256) and independently verifiable via `verify_chain()`.
- **Idempotency locking**: a WAL-backed claim is acquired before any Razorpay call — retries and duplicate requests can't double-charge.
- **Least-privilege data access**: every transaction/audit read is scoped to the authenticated principal's `user_id`/`agent_id` — no cross-tenant access.
- **Fail-closed on ambiguity**: authorization revoked/expired/mismatched, policy violations, catalog mismatches, and unknown Razorpay outcomes all block execution rather than guessing.

## Project structure

```text
api/            FastAPI transport layer (routes, auth dependency)
application/    Orchestrator — the one place that decides step order
engine/         Authorization, policy, hashing, mandate, idempotency,
                audit trail, transaction store, reconciliation
integrations/   Claude / Groq intent parsers, Razorpay REST client
models/         Pydantic models shared across layers
webhooks/       Razorpay webhook signature verification + parsing
recovery/       Stockout/refund/reroute recovery flow
frontend/       React + TypeScript demo dashboard (pipeline visualizer)
scripts/        Demo data seeding, Groq smoke test
tests/          334+ tests covering every engine, the orchestrator,
                the API, and adversarial/edge cases
```

## Getting started

### Prerequisites

- Python 3.12+
- Node.js 18+ (only needed for the frontend dashboard)
- A [Groq API key](https://console.groq.com) (free tier works)
- Razorpay **test-mode** API keys ([dashboard](https://dashboard.razorpay.com))

### 1. Backend setup

```bash
git clone <this-repo>
cd agentshield-main

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Description |
|---|---|
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Razorpay **test-mode** credentials |
| `RAZORPAY_WEBHOOK_SECRET` | Set when configuring the webhook in Razorpay dashboard |
| `MANDATE_SECRET_KEY` | ≥32 random bytes — signs every mandate |
| `AGENTSHIELD_API_TOKEN` | ≥32 random chars — Bearer token for `/v1/*` endpoints |
| `AGENTSHIELD_API_USER_ID` / `AGENTSHIELD_API_AGENT_ID` | Demo principal identity |
| `GROQ_API_KEY` / `GROQ_MODEL` | LLM used for intent interpretation |
| `AGENTSHIELD_DEMO_MODE` | `true` to use a permissive demo policy; keep `false` for fail-closed default |

Generate strong random values quickly:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Seed demo data (authorization + catalog)

```bash
python -m scripts.seed_demo_data
```

This creates a demo `AgentAuthorization` (max ₹5,000, `shoe_001` only, `merchant_001`) matching the frontend's sample requests.

### 4. Run the tests

```bash
pytest -q
```

All engine, orchestrator, API, and adversarial-edge-case tests should pass (334+).

### 5. Run the API

```bash
uvicorn server:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

### 6. Call the governed execution endpoint

```bash
curl -X POST http://localhost:8000/v1/agent/execute \
  -H "Authorization: Bearer $AGENTSHIELD_API_TOKEN" \
  -H "Idempotency-Key: demo-key-001" \
  -H "Content-Type: application/json" \
  -d '{"user_message": "Buy exactly one shoe_001 from merchant_001 for ₹4500."}'
```

A request outside the seeded authorization (e.g. a higher amount or a different SKU) is rejected before it ever reaches Razorpay — check the response and the `/v1/transactions/{id}/audit` trail to see exactly which layer blocked it.

### 7. Run the frontend dashboard (optional)

```bash
cd frontend
npm install
npm run dev
```

Visit the printed local URL to see the live pipeline visualization (Authorization → Policy → Mandate → Idempotency → Razorpay) for the approved and blocked demo requests.

### 8. Razorpay webhooks (for full reconciliation)

Point Razorpay's test-mode webhook at `POST /webhooks/razorpay` (use a tunnel like `ngrok` for local testing) and set the same secret in `RAZORPAY_WEBHOOK_SECRET`. Verified `payment.captured` / `payment.failed` events are reconciled against the transaction store and appended to the audit trail.

## API surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /healthz` | none | Liveness check |
| `POST /v1/agent/execute` | Bearer | Run the full governance pipeline for one user message |
| `GET /v1/transactions/{id}` | Bearer | Fetch a governed transaction (scoped to the caller) |
| `GET /v1/transactions/{id}/audit` | Bearer | Fetch the transaction's hash-chained audit trail |
| `POST /webhooks/razorpay` | HMAC signature | Razorpay payment event reconciliation |

`POST /v1/agent/execute` requires an `Idempotency-Key` header; replaying the same key returns a conflict rather than a second charge.

## Known limitations

- SQLite (WAL mode) is used for all persistence — appropriate for a single-process demo, not for horizontal scale-out.
- The frontend ships two hardcoded demo amounts (approved/blocked) to make the pipeline legible in a live demo; it is not a general-purpose checkout UI.
- Adversarial/prompt-injection testing of the LLM intent-parsing layer itself is not yet part of the automated test suite (the mitigation — never trusting model-owned identity or authorization fields — is tested; the parser's robustness to injected instructions is not).

## License

See repository license, if provided.