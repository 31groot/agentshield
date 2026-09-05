from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import groq
from groq import Groq

from integrations.intent_parser import SYSTEM_PROMPT
from models.intent import AgentRequestAnalysis


class GroqIntentParserError(ValueError):
    """
    Base exception for Groq intent-parsing failures.

    Inherits from ValueError so existing callers that catch
    ValueError around intent parsing keep working unchanged.
    """


class GroqRateLimitError(GroqIntentParserError):
    """
    Raised when Groq rate-limits the request (HTTP 429).

    AgentShield treats this as a retryable, fail-closed condition:
    no intent is produced, so no downstream governance step runs.
    """


class GroqAuthenticationError(GroqIntentParserError):
    """
    Raised when Groq rejects the configured API key.
    """


class GroqNetworkError(GroqIntentParserError):
    """
    Raised when AgentShield cannot reach Groq (timeout/connection error).
    """


class GroqResponseError(GroqIntentParserError):
    """
    Raised when Groq returns a malformed, empty, or unusable response.
    """


class GroqIntentParser:
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

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
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
                        "strict": True,
                        "schema": AgentRequestAnalysis.model_json_schema(),
                    },
                },
            )

        except groq.RateLimitError as exc:
            # Groq API quota/limit reached (HTTP 429).
            raise GroqRateLimitError(
                "Groq API rate limit reached. "
                "No intent was produced; the request was not executed."
            ) from exc

        except groq.AuthenticationError as exc:
            raise GroqAuthenticationError(
                "Groq API rejected the configured API key."
            ) from exc

        except (
            groq.APIConnectionError,
            groq.APITimeoutError,
        ) as exc:
            raise GroqNetworkError(
                "Could not reach Groq API "
                "(connection error or timeout)."
            ) from exc

        except groq.APIStatusError as exc:

            raise GroqIntentParserError(
                f"Groq API returned an error status: {exc.status_code}"
            ) from exc

        content = response.choices[0].message.content

        if not content:
            raise GroqResponseError(
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
            raise GroqResponseError(
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