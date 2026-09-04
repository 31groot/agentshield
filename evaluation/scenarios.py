from __future__ import annotations

from models.evaluation import EvaluationCase, EvaluationOutcome


BASE = {
    "user_id": "user_123",
    "agent_id": "agent_001",
    "merchant_id": "merchant_001",
    "amount_paise": 450000,
    "currency": "INR",
    "sku": "shoe_001",
    "quantity": 1,
    "authorization_max_amount_paise": 500000,
    "authorization_max_quantity": 2,
    "authorization_merchant_allowed": True,
    "authorization_sku_allowed": True,
    "authorization_active": True,
    "authorization_revoked": False,
    "policy_max_amount_paise": 500000,
    "policy_min_amount_paise": 10000,
    "policy_max_quantity": 10,
    "policy_bank_rail_available": True,
    "catalog_exists": True,
    "catalog_merchant_matches": True,
    "catalog_currency_matches": True,
    "catalog_stock": 10,
    "catalog_category_matches": True,
}


def _case(
    case_id: str,
    category: str,
    description: str,
    *,
    expected_outcome: EvaluationOutcome,
    **overrides: object,
) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        category=category,
        description=description,
        expected_outcome=expected_outcome,
        **{
            **BASE,
            **overrides,
        },
    )


def build_evaluation_cases() -> list[EvaluationCase]:
    cases = [
        _case(
            "happy_path",
            "authorization",
            "Valid purchase inside authorization and policy bounds.",
            expected_outcome=EvaluationOutcome.ALLOW,
        ),
        _case(
            "amount_above_authorization",
            "authorization",
            "Requested amount exceeds authorization limit.",
            expected_outcome=EvaluationOutcome.BLOCK,
            amount_paise=850000,
        ),
        _case(
            "quantity_above_authorization",
            "authorization",
            "Requested quantity exceeds authorization limit.",
            expected_outcome=EvaluationOutcome.BLOCK,
            quantity=3,
        ),
        _case(
            "merchant_not_allowed",
            "authorization",
            "Requested merchant is outside authorization.",
            expected_outcome=EvaluationOutcome.BLOCK,
            authorization_merchant_allowed=False,
        ),
        _case(
            "sku_not_allowed",
            "authorization",
            "Requested SKU is outside authorization.",
            expected_outcome=EvaluationOutcome.BLOCK,
            authorization_sku_allowed=False,
        ),
        _case(
            "authorization_inactive",
            "authorization",
            "Inactive authorization must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            authorization_active=False,
        ),
        _case(
            "authorization_revoked",
            "authorization",
            "Revoked authorization must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            authorization_revoked=True,
        ),
        _case(
            "policy_amount_limit",
            "policy",
            "Policy amount limit is below requested amount.",
            expected_outcome=EvaluationOutcome.BLOCK,
            amount_paise=450001,
            policy_max_amount_paise=450000,
        ),
        _case(
            "policy_minimum",
            "policy",
            "Requested amount is below policy minimum.",
            expected_outcome=EvaluationOutcome.BLOCK,
            amount_paise=5000,
        ),
        _case(
            "policy_quantity_limit",
            "policy",
            "Requested quantity exceeds policy limit.",
            expected_outcome=EvaluationOutcome.BLOCK,
            quantity=11,
        ),
        _case(
            "bank_rail_unavailable",
            "policy",
            "Unavailable bank rail must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            policy_bank_rail_available=False,
        ),
        _case(
            "catalog_missing",
            "catalog",
            "Unknown product must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            catalog_exists=False,
        ),
        _case(
            "catalog_merchant_mismatch",
            "catalog",
            "Catalog merchant mismatch must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            catalog_merchant_matches=False,
        ),
        _case(
            "catalog_currency_mismatch",
            "catalog",
            "Catalog currency mismatch must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            catalog_currency_matches=False,
        ),
        _case(
            "catalog_out_of_stock",
            "catalog",
            "Out-of-stock product must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            catalog_stock=0,
        ),
        _case(
            "catalog_category_mismatch",
            "catalog",
            "Catalog category outside the policy category scope must block execution.",
            expected_outcome=EvaluationOutcome.BLOCK,
            catalog_category_matches=False,
        ),
    ]

    for amount in (
        10000,
        25000,
        50000,
        100000,
        200000,
        300000,
        400000,
        450000,
        490000,
        500000,
    ):
        cases.append(
            _case(
                f"amount_boundary_{amount}",
                "boundary",
                f"Valid authorization amount boundary: {amount} paise.",
                expected_outcome=EvaluationOutcome.ALLOW,
                amount_paise=amount,
            )
        )

    for quantity in (1, 2):
        cases.append(
            _case(
                f"quantity_allowed_{quantity}",
                "boundary",
                f"Authorization allows quantity {quantity}.",
                expected_outcome=EvaluationOutcome.ALLOW,
                quantity=quantity,
                amount_paise=450000,
            )
        )

    for quantity in range(3, 11):
        cases.append(
            _case(
                f"quantity_authorization_exceeded_{quantity}",
                "boundary",
                f"Authorization rejects quantity {quantity}.",
                expected_outcome=EvaluationOutcome.BLOCK,
                quantity=quantity,
            )
        )

    for index in range(1, 36):
        cases.append(
            _case(
                f"valid_synthetic_{index:02d}",
                "synthetic",
                f"Valid deterministic purchase scenario {index}.",
                expected_outcome=EvaluationOutcome.ALLOW,
                amount_paise=450000,
                quantity=1,
            )
        )

    return cases
