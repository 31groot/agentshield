from datetime import datetime, timezone

from engine.policy import DeterministicPolicyEngine
from models.intent import AuthorizationInterpretation, IntentProposal
from models.policy import TransactionPolicy


def make_proposal(**overrides) -> IntentProposal:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "intent_id": "intent_001",
        "raw_user_prompt": "Buy running shoes under ₹5000.",
        "merchant_id": "merchant_001",
        "requested_amount_inr": 4500.0,
        "currency": "INR",
        "items": [
            {
                "sku": "shoe_001",
                "quantity": 1,
            }
        ],
        "action_type": "CREATE_ORDER",
        "nonce": "nonce_001",
        "created_at": datetime.now(timezone.utc),
        "ttl_seconds": 300,
    }

    payload.update(overrides)

    return IntentProposal.model_validate(payload)


def make_authorization(**overrides) -> AuthorizationInterpretation:
    payload = {
        "max_amount_inr": 5000.0,
        "currency": "INR",
        "product_constraints": ["running shoes"],
        "allowed_merchants": [],
        "max_quantity": 1,
        "constraints": [
            "purchase must be running shoes",
            "maximum amount ₹5000",
        ],
    }

    payload.update(overrides)

    return AuthorizationInterpretation.model_validate(payload)


def make_policy(**overrides) -> TransactionPolicy:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "max_amount_inr": 5000.0,
        "min_amount_inr": 100.0,
        "allowed_merchants": ["merchant_001"],
        "allowed_categories": [],
        "allowed_skus": ["shoe_001", "shoe_002"],
        "max_quantity": 2,
        "currency": "INR",
        "bank_rail_available": True,
    }

    payload.update(overrides)

    return TransactionPolicy.model_validate(payload)


def evaluate(
    proposal=None,
    authorization=None,
    policy=None,
):
    return DeterministicPolicyEngine().evaluate(
        proposal or make_proposal(),
        authorization or make_authorization(),
        policy or make_policy(),
    )


def test_valid_transaction_is_approved():
    result = evaluate()

    assert result.allowed is True
    assert result.reason == "POLICY_APPROVED"


def test_amount_above_policy_limit_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            requested_amount_inr=5500.0
        )
    )

    assert result.allowed is False
    assert result.reason == "AMOUNT_EXCEEDS_POLICY_LIMIT"


def test_amount_above_user_authorization_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            requested_amount_inr=4800.0
        ),
        authorization=make_authorization(
            max_amount_inr=4500.0
        ),
        policy=make_policy(
            max_amount_inr=5000.0
        ),
    )

    assert result.allowed is False
    assert result.reason == "AMOUNT_EXCEEDS_USER_AUTHORIZATION"


def test_amount_below_economic_floor_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            requested_amount_inr=50.0
        )
    )

    assert result.allowed is False
    assert result.reason == "AMOUNT_BELOW_ECONOMIC_FLOOR"


def test_unapproved_merchant_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            merchant_id="merchant_999"
        )
    )

    assert result.allowed is False
    assert result.reason == "MERCHANT_NOT_ALLOWED"


def test_user_merchant_restriction_is_enforced():
    result = evaluate(
        proposal=make_proposal(
            merchant_id="merchant_002"
        ),
        authorization=make_authorization(
            allowed_merchants=["merchant_001"]
        ),
        policy=make_policy(
            allowed_merchants=["merchant_001", "merchant_002"]
        ),
    )

    assert result.allowed is False
    assert result.reason == "MERCHANT_NOT_AUTHORIZED_BY_USER"


def test_quantity_above_policy_limit_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 5,
                }
            ]
        ),
        policy=make_policy(
            max_quantity=2
        ),
    )

    assert result.allowed is False
    assert result.reason == "QUANTITY_EXCEEDS_POLICY_LIMIT"


def test_quantity_above_user_authorization_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 2,
                }
            ]
        ),
        authorization=make_authorization(
            max_quantity=1
        ),
        policy=make_policy(
            max_quantity=5
        ),
    )

    assert result.allowed is False
    assert result.reason == "QUANTITY_EXCEEDS_USER_AUTHORIZATION"


def test_total_quantity_across_multiple_items_is_checked():
    result = evaluate(
        proposal=make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 2,
                },
                {
                    "sku": "shoe_002",
                    "quantity": 2,
                },
            ]
        ),
        policy=make_policy(
            allowed_skus=["shoe_001", "shoe_002"],
            max_quantity=3,
        ),
    )

    assert result.allowed is False
    assert result.reason == "QUANTITY_EXCEEDS_POLICY_LIMIT"


def test_unapproved_sku_is_blocked():
    result = evaluate(
        proposal=make_proposal(
            items=[
                {
                    "sku": "detergent_001",
                    "quantity": 1,
                }
            ]
        )
    )

    assert result.allowed is False
    assert result.reason == "SKU_NOT_ALLOWED"


def test_bank_downtime_blocks_transaction():
    result = evaluate(
        policy=make_policy(
            bank_rail_available=False
        )
    )

    assert result.allowed is False
    assert result.reason == "BANK_RAIL_UNAVAILABLE"


def test_user_and_agent_must_match_policy():
    result = evaluate(
        proposal=make_proposal(
            user_id="attacker"
        )
    )

    assert result.allowed is False
    assert result.reason == "USER_POLICY_MISMATCH"


def test_agent_and_policy_must_match():
    result = evaluate(
        proposal=make_proposal(
            agent_id="unknown_agent"
        )
    )

    assert result.allowed is False
    assert result.reason == "AGENT_POLICY_MISMATCH"


def test_stricter_of_policy_and_user_limit_wins():
    result = evaluate(
        proposal=make_proposal(
            requested_amount_inr=4800.0
        ),
        authorization=make_authorization(
            max_amount_inr=5000.0
        ),
        policy=make_policy(
            max_amount_inr=4500.0
        ),
    )

    assert result.allowed is False
    assert result.reason == "AMOUNT_EXCEEDS_POLICY_LIMIT"