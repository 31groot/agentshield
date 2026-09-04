# AgentShield APEX

Deterministic governance and control plane for AI-initiated Razorpay payments.

AgentShield sits between an AI agent and the payment rail. The model interprets natural-language intent, while server-owned controls decide whether money is allowed to move.

## Core principle

The LLM does not hold payment authority.

The execution path is:

```text
User request
    ↓
Groq intent interpretation
    ↓
Strict Pydantic validation
    ↓
Server-owned authentication
    ↓
Server-owned authorization
    ↓
Deterministic policy
    ↓
Intent hash
    ↓
AP2-aligned mandate
    ↓
Idempotency claim
    ↓
Razorpay order creation
    ↓
Webhook verification
    ↓
Reconciliation + audit