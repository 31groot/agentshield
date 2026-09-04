from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from groq import Groq

from integrations.claude import ClaudeIntentParser
from models.intent import AgentRequestAnalysis


class GroqIntentParser(ClaudeIntentParser):
    """
    Groq-backed implementation of AgentShield intent parsing.

    The model interprets the request only.
    Authorization and financial execution remain server-owned.
    """

    def __init__(
        self,
        client: Groq,
        model: str,
    ) -> None:
        self._client = client
        self._model = model

    @staticmethod
    def _normalize_datetime_fields(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Normalize JSON datetime strings emitted by the LLM into
        Python datetime objects before strict Pydantic validation.
        """
        intent_proposal = payload.get("intent_proposal")

        if not isinstance(intent_proposal, dict):
            return payload

        created_at = intent_proposal.get("created_at")

        if isinstance(created_at, str):
            intent_proposal["created_at"] = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )

        return payload

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
            raise ValueError(
                "user_message cannot be empty"
            )

        context = merchant_context or {}

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": self.SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        "Interpret the following transaction request.\n\n"
                        f"Merchant context:\n{context}\n\n"
                        f"User request:\n{user_message}"
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_request_analysis",
                    "strict": False,
                    "schema": AgentRequestAnalysis.model_json_schema(),
                },
            },
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError(
                "Groq did not return a valid AgentRequestAnalysis"
            )

        try:
            payload = json.loads(content)

            if not isinstance(payload, dict):
                raise ValueError(
                    "Groq response must be a JSON object"
                )

            payload = self._normalize_datetime_fields(payload)

            analysis = AgentRequestAnalysis.model_validate(
                payload
            )

        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Groq did not return a valid AgentRequestAnalysis"
            ) from exc

        # AgentShield owns these fields.
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