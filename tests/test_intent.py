import pytest
from pydantic import ValidationError

from models.intent import IntentProposal


def make_valid_intent(**overrides) -> dict:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "intent_id": "intent_001",
        "merchant_id": "merchant_001",
        "requested_amount_inr": 450.0,
        "currency": "INR",
        "sku_list": ["apple_organic_001"],
        "action_type": "CREATE_ORDER",
        "nonce": "nonce_abc123",
        "ttl_seconds": 300,
    }

    payload.update(overrides)
    return payload


def test_valid_intent_proposal():
    proposal = IntentProposal.model_validate(
        make_valid_intent()
    )

    assert proposal.user_id == "user_123"
    assert proposal.agent_id == "agent_001"
    assert proposal.intent_id == "intent_001"
    assert proposal.requested_amount_inr == 450.0
    assert proposal.currency == "INR"
    assert proposal.action_type == "CREATE_ORDER"


def test_missing_user_id_is_rejected():
    payload = make_valid_intent()
    del payload["user_id"]

    with pytest.raises(ValidationError):
        IntentProposal.model_validate(payload)


def test_negative_amount_is_rejected():
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


def test_non_inr_currency_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                currency="USD"
            )
        )


def test_empty_sku_list_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                sku_list=[]
            )
        )


def test_non_string_action_type_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                action_type=123
            )
        )


def test_blank_action_type_is_rejected():
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            make_valid_intent(
                action_type=""
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
                sku_list=[""]
            )
        )