from __future__ import annotations

import json

import pytest

from integrations.groq import GroqIntentParser

from datetime import datetime


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeChat:
    def __init__(self, response: FakeResponse):
        self.completions = FakeCompletions(response)


class FakeGroq:
    def __init__(self, response: FakeResponse):
        self.chat = FakeChat(response)


def valid_analysis_payload() -> dict:
    return {
        "raw_user_prompt": "model prompt",
        "authorization": {
            "max_amount_paise": 500000,
            "currency": "INR",
            "product_constraints": ["running shoes"],
            "allowed_merchants": ["merchant_001"],
            "max_quantity": 2,
            "constraints": ["must be footwear"],
        },
        "intent_proposal": {
            "user_id": "model_user",
            "agent_id": "model_agent",
            "intent_id": "model_intent",
            "raw_user_prompt": "model prompt",
            "merchant_id": "merchant_001",
            "amount_paise": 450000,
            "currency": "INR",
            "items": [
                {
                    "sku": "shoe_001",
                    "quantity": 1,
                }
            ],
            "action_type": "CREATE_ORDER",
            "nonce": "nonce_001",
        },
    }


def make_parser(response: FakeResponse) -> tuple[
    GroqIntentParser,
    FakeGroq,
]:
    client = FakeGroq(response)

    parser = GroqIntentParser(
        client=client,
        model="openai/gpt-oss-120b",
    )

    return parser, client


def test_groq_parser_parses_structured_response():
    parser, _client = make_parser(
        FakeResponse(
            json.dumps(valid_analysis_payload())
        )
    )

    result = parser.parse(
        user_message="Buy running shoes under ₹5000.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        merchant_context={
            "merchant_id": "merchant_001",
        },
    )

    assert result.raw_user_prompt == (
        "Buy running shoes under ₹5000."
    )

    assert result.authorization is not None
    assert result.authorization.max_amount_paise == 500000
    assert result.authorization.currency == "INR"
    assert result.authorization.allowed_merchants == [
        "merchant_001"
    ]
    assert result.authorization.max_quantity == 2

    assert result.intent_proposal.user_id == "user_123"
    assert result.intent_proposal.agent_id == "agent_001"
    assert result.intent_proposal.intent_id == "intent_001"
    assert result.intent_proposal.raw_user_prompt == (
        "Buy running shoes under ₹5000."
    )

    assert result.intent_proposal.merchant_id == "merchant_001"
    assert result.intent_proposal.amount_paise == 450000
    assert result.intent_proposal.currency == "INR"


def test_groq_parser_overrides_model_identity():
    parser, _client = make_parser(
        FakeResponse(
            json.dumps(valid_analysis_payload())
        )
    )

    result = parser.parse(
        user_message="Buy shoes.",
        user_id="server_user",
        agent_id="server_agent",
        intent_id="server_intent",
    )

    assert result.intent_proposal.user_id == "server_user"
    assert result.intent_proposal.agent_id == "server_agent"
    assert result.intent_proposal.intent_id == "server_intent"
    assert result.intent_proposal.raw_user_prompt == "Buy shoes."

    # The model's identity must never become authoritative.
    assert result.intent_proposal.user_id != "model_user"
    assert result.intent_proposal.agent_id != "model_agent"
    assert result.intent_proposal.intent_id != "model_intent"


def test_groq_parser_sends_expected_model():
    parser, client = make_parser(
        FakeResponse(
            json.dumps(valid_analysis_payload())
        )
    )

    parser.parse(
        user_message="Buy shoes.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
    )

    calls = client.chat.completions.calls

    assert len(calls) == 1
    assert calls[0]["model"] == "openai/gpt-oss-120b"

    assert calls[0]["response_format"]["type"] == (
        "json_schema"
    )

    assert (
        calls[0]["response_format"]["json_schema"]["name"]
        == "agent_request_analysis"
    )


def test_groq_parser_passes_merchant_context():
    parser, client = make_parser(
        FakeResponse(
            json.dumps(valid_analysis_payload())
        )
    )

    parser.parse(
        user_message="Buy shoes.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
        merchant_context={
            "merchant_id": "merchant_001",
            "category": "footwear",
        },
    )

    call = client.chat.completions.calls[0]

    user_message = call["messages"][1]["content"]

    assert "merchant_001" in user_message
    assert "footwear" in user_message
    assert "Buy shoes." in user_message


def test_groq_parser_rejects_blank_request():
    parser, _client = make_parser(
        FakeResponse(
            json.dumps(valid_analysis_payload())
        )
    )

    with pytest.raises(
        ValueError,
        match="user_message cannot be empty",
    ):
        parser.parse(
            user_message="   ",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
        )


def test_groq_parser_rejects_invalid_json():
    parser, _client = make_parser(
        FakeResponse("not valid json")
    )

    with pytest.raises(
        ValueError,
        match=(
            "Groq did not return a valid "
            "AgentRequestAnalysis"
        ),
    ):
        parser.parse(
            user_message="Buy shoes.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
        )


def test_groq_parser_rejects_invalid_schema():
    invalid_payload = valid_analysis_payload()

    del invalid_payload["intent_proposal"]["merchant_id"]

    parser, _client = make_parser(
        FakeResponse(
            json.dumps(invalid_payload)
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "Groq did not return a valid "
            "AgentRequestAnalysis"
        ),
    ):
        parser.parse(
            user_message="Buy shoes.",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
        )

def test_groq_parser_accepts_datetime_string_from_model():
    payload = valid_analysis_payload()

    payload["intent_proposal"]["created_at"] = (
        "2026-09-04T12:00:00Z"
    )

    parser, _client = make_parser(
        FakeResponse(json.dumps(payload))
    )

    result = parser.parse(
        user_message="Buy shoes.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
    )

    assert isinstance(
        result.intent_proposal.created_at,
        datetime,
    )

    assert (
        result.intent_proposal.created_at.isoformat()
        == "2026-09-04T12:00:00+00:00"
    )