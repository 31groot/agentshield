from __future__ import annotations

from typing import Any

import anthropic
from anthropic import Anthropic

from integrations.intent_parser import SYSTEM_PROMPT
from models.intent import AgentRequestAnalysis


class ClaudeIntentParser:
    """
    Anthropic-backed implementation of AgentShield intent parsing.

    The model interprets the request only.
    Authorization and financial execution remain server-owned.
    """

    def __init__(
        self,
        client: Anthropic,
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
        user_message = user_message.strip()

        if not user_message:
            raise ValueError("user_message cannot be empty")

        context = merchant_context or {}

        response = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
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

        return AgentRequestAnalysis(
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
