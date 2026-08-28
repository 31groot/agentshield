from __future__ import annotations

from typing import Any

import anthropic

from models.intent import IntentProposal


class ClaudeIntentParser:


    SYSTEM_PROMPT = """
You are the intent interpretation component of AgentShield APEX.

Your ONLY responsibility is to understand the user's request and
produce a structured transaction proposal.

You may:
- understand natural-language intent
- identify requested products
- identify merchant information when available
- identify requested transaction amount
- identify quantity
- identify the requested financial action

You MUST NOT:
- execute payments
- call Razorpay
- create refunds
- create payouts
- change user authorization
- invent spending authority
- bypass any AgentShield policy

The output is only a PROPOSAL.

AgentShield will independently validate, authorize, govern,
sign, and execute the proposed action.
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
    ) -> IntentProposal:
        """
        Convert a user request into a validated IntentProposal.
        
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
                        "Interpret the following user request.\n\n"
                        f"User ID: {user_id}\n"
                        f"Agent ID: {agent_id}\n"
                        f"Intent ID: {intent_id}\n\n"
                        f"Merchant context:\n{context}\n\n"
                        f"User request:\n{user_message}"
                    ),
                }
            ],
            output_format=IntentProposal,
        )

        if response.parsed_output is None:
            raise ValueError(
                "Claude did not return a valid IntentProposal"
            )

        return response.parsed_output