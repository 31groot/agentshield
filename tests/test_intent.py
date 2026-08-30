from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from integrations.claude import ClaudeIntentParser
from models.intent import (
    AgentRequestAnalysis,
    AuthorizationInterpretation,
    IntentProposal,
)


def make_valid_authorization(**overrides) -> dict:
    payload = {
        "max_amount_inr": 500.0,
        "currency": "INR",
        "product_constraints": ["organic apples"],
        "allowed_merchants": [],
        "max_quantity": 2,
        "constraints": ["organic"],
    }

    payload.update(overrides)
    return payload


def make_valid_intent(**overrides) -> dict:
    payload = {
        "user_id": "claude_should_not_control_this",
        "agent_id": "claude_should_not_control_this",
        "intent_id": "claude_should_not_control_this",
        "raw_user_prompt": "claude_should_not_control_this",
        "merchant_id": "merchant_001",
        "requested_amount_inr": 450.0,
        "currency": "INR",
                "items": [
            {
                "sku": "apple_organic_001",
                "quantity": 2,
            }
        ],
        "action_type": "CREATE_ORDER",
        "nonce": "nonce_abc123",
        "ttl_seconds": 300,
    }

    payload.update(overrides)
    return payload


def make_valid_analysis(**overrides) -> AgentRequestAnalysis:
    authorization = make_valid_authorization()
    intent = make_valid_intent()

    authorization.update(
        overrides.pop("authorization", {})
    )

    intent.update(
        overrides.pop("intent_proposal", {})
    )

    return AgentRequestAnalysis(
        raw_user_prompt=overrides.pop(
            "raw_user_prompt",
            "claude_should_not_control_this",
        ),
        authorization=AuthorizationInterpretation.model_validate(
            authorization
        ),
        intent_proposal=IntentProposal.model_validate(
            intent
        ),
    )


class FakeMessages:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs

        return SimpleNamespace(
            parsed_output=self.parsed_output
        )


class FakeClaudeClient:
    def __init__(self, parsed_output):
        self.messages = FakeMessages(parsed_output)


def test_claude_output_becomes_agent_request_analysis():
    response = make_valid_analysis()

    client = FakeClaudeClient(response)

    parser = ClaudeIntentParser(
        client=client,
        model="test-model",
    )

    analysis = parser.parse(
        "Buy two organic apples for me.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
    )

    assert isinstance(analysis, AgentRequestAnalysis)

    assert analysis.raw_user_prompt == (
        "Buy two organic apples for me."
    )

    assert analysis.authorization.max_amount_inr == 500.0

    assert (
        analysis.intent_proposal.merchant_id
        == "merchant_001"
    )

    assert (
        analysis.intent_proposal.requested_amount_inr
        == 450.0
    )

    assert analysis.intent_proposal.items[0].quantity == 2

    assert (
        analysis.intent_proposal.action_type
        == "CREATE_ORDER"
    )


def test_server_owned_fields_override_claude_output():
    response = make_valid_analysis(
        raw_user_prompt="CLAUDE'S FAKE PROMPT",
        intent_proposal={
            "user_id": "fake_user",
            "agent_id": "fake_agent",
            "intent_id": "fake_intent",
            "raw_user_prompt": "CLAUDE'S FAKE PROMPT",
        },
    )

    client = FakeClaudeClient(response)

    parser = ClaudeIntentParser(
        client=client,
        model="test-model",
    )

    analysis = parser.parse(
        "Buy apples.",
        user_id="real_user",
        agent_id="real_agent",
        intent_id="real_intent",
    )

    assert analysis.raw_user_prompt == "Buy apples."

    assert analysis.intent_proposal.user_id == "real_user"
    assert analysis.intent_proposal.agent_id == "real_agent"
    assert analysis.intent_proposal.intent_id == "real_intent"
    assert analysis.intent_proposal.raw_user_prompt == "Buy apples."


def test_empty_user_message_is_rejected():
    response = make_valid_analysis()

    client = FakeClaudeClient(response)

    parser = ClaudeIntentParser(
        client=client,
        model="test-model",
    )

    with pytest.raises(
        ValueError,
        match="user_message cannot be empty",
    ):
        parser.parse(
            "   ",
            user_id="user_123",
            agent_id="agent_001",
            intent_id="intent_001",
        )


def test_invalid_amount_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                requested_amount_inr=-100.0
            )
        )

def test_zero_amount_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                requested_amount_inr=0.0
            )
        )


def test_empty_sku_list_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                items=[]
            )
        )


def test_blank_action_type_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                action_type=""
            )
        )


def test_non_string_action_type_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                action_type=123
            )
        )


def test_ttl_cannot_exceed_600_seconds():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                ttl_seconds=601
            )
        )


def test_extra_fields_are_rejected():
    payload = make_valid_intent()

    payload["razorpay_key_secret"] = "DO_NOT_ALLOW_THIS"

    with pytest.raises(ValidationError):
        IntentProposal.model_validate(payload)


def test_blank_sku_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                items=[
                    {
                        "sku": "",
                        "quantity": 1,
                    }
                ]
            )
        )


def test_claude_request_does_not_contain_server_secrets():
    response = make_valid_analysis()

    client = FakeClaudeClient(response)

    parser = ClaudeIntentParser(
        client=client,
        model="test-model",
    )

    parser.parse(
        "Buy two apples.",
        user_id="user_123",
        agent_id="agent_001",
        intent_id="intent_001",
    )

    kwargs = client.messages.last_kwargs

    assert kwargs is not None

    serialized = str(kwargs)

    assert "RAZORPAY_KEY_SECRET" not in serialized
    assert "RAZORPAY_KEY_ID" not in serialized

def test_multiple_items_have_individual_quantities():
    proposal = IntentProposal.model_validate(
        make_valid_intent(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 2,
                },
                {
                    "sku": "sock_001",
                    "quantity": 3,
                },
            ]
        )
    )

    assert len(proposal.items) == 2
    assert proposal.items[0].sku == "shoe_001"
    assert proposal.items[0].quantity == 2
    assert proposal.items[1].sku == "sock_001"
    assert proposal.items[1].quantity == 3

def test_empty_items_are_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                items=[]
            )
        )

def test_empty_item_sku_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                items=[
                    {
                        "sku": "",
                        "quantity": 1,
                    }
                ]
            )
        )
def test_zero_item_quantity_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                items=[
                    {
                        "sku": "shoe_001",
                        "quantity": 0,
                    }
                ]
            )
        )