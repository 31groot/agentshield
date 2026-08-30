from __future__ import annotations

from typing import Any

import anthropic

from models.intent import AgentRequestAnalysis


class ClaudeIntentParser:

    SYSTEM_PROMPT = """
You are the intent interpretation component of AgentShield APEX.

Your ONLY responsibility is to interpret the user's natural-language
request and produce a structured transaction analysis.

Your response contains two separate concepts:

1. authorization
   Interpret what the user appears to authorize based ONLY on
   the user's request.

2. intent_proposal
   Describe the concrete transaction the user is requesting.

For intent_proposal:
- Return each product as a separate item.
- Each item must contain:
  - sku
  - quantity
- Do not use a single global quantity for multiple products.

For monetary values:
- Return amounts as integer paise.
- Do not return decimal rupee values.
- Example: ₹4,500 = 450000 paise.

The amount_paise field must represent the exact transaction amount
in Indian paise as an integer.

You may:
- understand natural-language intent
- identify requested products
- identify merchant information when available
- identify requested transaction amount
- identify quantity
- identify the requested financial action
- identify explicit user constraints

You MUST NOT:
- execute payments
- call Razorpay
- create refunds
- create payouts
- approve transactions
- decide whether a transaction is allowed
- invent spending authority
- bypass AgentShield policy
- assume authorization that the user did not express

Important:
Authorization interpretation is only an interpretation.
It is NOT an authorization decision.

AgentShield will independently validate, authorize, govern,
sign, and execute any proposed action.
"""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
    ) -> None:
        self._client = client
        self._model = model

    def parse(
        self,
        user_message: str,
        *,
        user_id: str,
        agent_id: str,
        intent_id: str,
        merchant_context: dict[str, Any] | None = None,
    ) -> AgentRequestAnalysis:
        """
        Convert a user request into a validated AgentRequestAnalysis.

        """

        user_message = user_message.strip()

        if not user_message:
            raise ValueError("user_message cannot be empty")

        context = merchant_context or {}

        response = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=self.SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Interpret the following transaction request.\n\n"
                        f"Merchant context:\n{context}\n\n"
                        f"User request:\n{user_message}"
                    ),
                }
            ],
            output_format=AgentRequestAnalysis,
        )

        analysis = response.parsed_output

        if analysis is None:
            raise ValueError(
                "Claude did not return a valid AgentRequestAnalysis"
            )

        # AgentShield owns these fields.
        # Claude is not trusted to determine them.
        analysis = AgentRequestAnalysis(
            raw_user_prompt=user_message,
            authorization=analysis.authorization,
            intent_proposal=analysis.intent_proposal.model_copy(
                update={
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "intent_id": intent_id,
                    "raw_user_prompt": user_message,
                }
            ),
        )

        return analysis