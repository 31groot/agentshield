from datetime import datetime, timezone

from engine.hashing import IntentHasher
from models.authorization import AgentAuthorization
from models.intent import AuthorizationInterpretation, IntentProposal

def make_authorization(
    **overrides,
) -> AgentAuthorization:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "authorization_id": "auth_001",
        "active": True,
        "revoked": False,
        "max_amount_paise": 500000,
        "allowed_merchants": ["merchant_001"],
        "allowed_categories": ["footwear"],
        "allowed_skus": ["shoe_001"],
        "max_quantity": 2,
        "currency": "INR",
        "created_at": datetime.now(timezone.utc),
        "expires_at": None,
    }

    payload.update(overrides)

    return AgentAuthorization.model_validate(payload)

def make_server_authorization(
    **overrides,
) -> AgentAuthorization:
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "authorization_id": "auth_001",
        "active": True,
        "revoked": False,
        "max_amount_paise": 500000,
        "allowed_merchants": ["merchant_001"],
        "allowed_categories": ["footwear"],
        "allowed_skus": ["shoe_001"],
        "max_quantity": 2,
        "currency": "INR",
        "created_at": datetime.now(timezone.utc),
        "expires_at": None,
    }

    payload.update(overrides)

    return AgentAuthorization.model_validate(payload)
def make_proposal(**overrides):
    payload = {
        "user_id": "user_123",
        "agent_id": "agent_001",
        "intent_id": "intent_001",
        "raw_user_prompt": "Buy running shoes under ₹5000.",
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
        "created_at": datetime.now(timezone.utc),
        "ttl_seconds": 300,
    }

    payload.update(overrides)

    return IntentProposal.model_validate(payload)


def test_same_input_produces_same_hash():
    hasher = IntentHasher()

    auth = make_authorization()
    proposal = make_proposal()

    hash_1 = hasher.hash(auth, proposal)
    hash_2 = hasher.hash(auth, proposal)

    assert hash_1 == hash_2


def test_amount_change_changes_hash():
    hasher = IntentHasher()

    auth = make_authorization()

    original = hasher.hash(
        auth,
        make_proposal(
            amount_paise=450000,
        ),
    )

    mutated = hasher.hash(
        auth,
        make_proposal(
            amount_paise=460000,
        ),
    )

    assert original != mutated


def test_merchant_change_changes_hash():
    hasher = IntentHasher()

    auth = make_authorization()

    original = hasher.hash(
        auth,
        make_proposal(
            merchant_id="merchant_001",
        ),
    )

    mutated = hasher.hash(
        auth,
        make_proposal(
            merchant_id="merchant_002",
        ),
    )

    assert original != mutated


def test_sku_change_changes_hash():
    hasher = IntentHasher()
    auth = make_authorization()

    original = hasher.hash(
        auth,
        make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 1,
                }
            ],
        ),
    )

    mutated = hasher.hash(
        auth,
        make_proposal(
            items=[
                {
                    "sku": "shoe_999",
                    "quantity": 1,
                }
            ],
        ),
    )

    assert original != mutated

def test_quantity_change_changes_hash():
    hasher = IntentHasher()
    auth = make_authorization()

    original = hasher.hash(
        auth,
        make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 1,
                }
            ],
        ),
    )

    mutated = hasher.hash(
        auth,
        make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 2,
                }
            ],
        ),
    )

    assert original != mutated


def test_authorization_limit_change_changes_hash():
    hasher = IntentHasher()

    proposal = make_proposal()

    original = hasher.hash(
        make_authorization(max_amount_paise=500000),
        proposal,
    )

    mutated = hasher.hash(
        make_authorization(max_amount_paise=600000),
        proposal,
    )

    assert original != mutated


def test_canonicalization_is_deterministic():
    hasher = IntentHasher()

    auth = make_authorization(
        allowed_merchants=[
            "merchant_002",
            "merchant_001",
        ],
        allowed_categories=[
            "electronics",
            "footwear",
        ],
        allowed_skus=[
            "shoe_002",
            "shoe_001",
        ],
    )

    proposal = make_proposal(
        items=[
            {
                "sku": "shoe_002",
                "quantity": 1,
            },
            {
                "sku": "shoe_001",
                "quantity": 2,
            },
        ],
    )

    canonical_1 = hasher.canonicalize(
        auth,
        proposal,
    )

    canonical_2 = hasher.canonicalize(
        auth,
        proposal,
    )

    assert canonical_1 == canonical_2


def test_raw_prompt_change_does_not_change_transaction_hash():


    hasher = IntentHasher()
    auth = make_authorization()

    hash_1 = hasher.hash(
        auth,
        make_proposal(
            raw_user_prompt="Buy running shoes under ₹5000.",
        ),
    )

    hash_2 = hasher.hash(
        auth,
        make_proposal(
            raw_user_prompt="Please get me running shoes below Rs 5000.",
        ),
    )

    assert hash_1 == hash_2

def test_item_order_does_not_change_hash():
    hasher = IntentHasher()
    auth = make_authorization()

    hash_1 = hasher.hash(
        auth,
        make_proposal(
            items=[
                {
                    "sku": "shoe_001",
                    "quantity": 1,
                },
                {
                    "sku": "sock_001",
                    "quantity": 2,
                },
            ],
        ),
    )

    hash_2 = hasher.hash(
        auth,
        make_proposal(
            items=[
                {
                    "sku": "sock_001",
                    "quantity": 2,
                },
                {
                    "sku": "shoe_001",
                    "quantity": 1,
                },
            ],
        ),
    )

    assert hash_1 == hash_2

def test_amount_paise_change_changes_hash():
    hasher = IntentHasher()
    authorization = make_authorization()

    original = hasher.hash(
        authorization,
        make_proposal(
            amount_paise=450000,
        ),
    )

    changed = hasher.hash(
        authorization,
        make_proposal(
            amount_paise=450100,
        ),
    )

    assert original != changed

def test_server_authorization_bounds_change_changes_hash():
    hasher = IntentHasher()

    proposal = make_proposal()

    original = hasher.hash(
        make_server_authorization(
            max_amount_paise=500000,
        ),
        proposal,
    )

    changed = hasher.hash(
        make_server_authorization(
            max_amount_paise=400000,
        ),
        proposal,
    )

    assert original != changed