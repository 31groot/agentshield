from __future__ import annotations

from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)


class EvaluationOutcome(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class EvaluationCase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    case_id: StrictStr = Field(min_length=1)
    category: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)

    expected_outcome: EvaluationOutcome

    user_id: StrictStr = Field(min_length=1)
    agent_id: StrictStr = Field(min_length=1)
    merchant_id: StrictStr = Field(min_length=1)
    amount_paise: StrictInt = Field(gt=0)
    currency: StrictStr = Field(min_length=3, max_length=3)
    sku: StrictStr = Field(min_length=1)
    quantity: StrictInt = Field(ge=1)

    authorization_max_amount_paise: StrictInt = Field(gt=0)
    authorization_max_quantity: StrictInt = Field(ge=1)
    authorization_merchant_allowed: StrictBool
    authorization_sku_allowed: StrictBool
    authorization_active: StrictBool = True
    authorization_revoked: StrictBool = False

    policy_max_amount_paise: StrictInt = Field(gt=0)
    policy_min_amount_paise: StrictInt = Field(ge=0)
    policy_max_quantity: StrictInt = Field(ge=1)
    policy_category_allowed: StrictBool = True
    policy_bank_rail_available: StrictBool = True

    catalog_exists: StrictBool = True
    catalog_merchant_matches: StrictBool = True
    catalog_currency_matches: StrictBool = True
    catalog_stock: StrictInt = Field(ge=0)
    catalog_category_matches: StrictBool = True


class EvaluationResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    case_id: StrictStr = Field(min_length=1)
    category: StrictStr = Field(min_length=1)

    expected_outcome: EvaluationOutcome
    actual_outcome: EvaluationOutcome

    expected_reason: StrictStr = Field(min_length=1)
    actual_reason: StrictStr = Field(min_length=1)

    authorization_allowed: StrictBool
    policy_allowed: StrictBool

    razorpay_called: StrictBool
    execution_attempted: StrictBool
    unsafe_execution: StrictBool

    final_state: StrictStr = Field(min_length=1)
    passed: StrictBool


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    total_cases: StrictInt = Field(ge=0)
    passed_cases: StrictInt = Field(ge=0)
    failed_cases: StrictInt = Field(ge=0)

    unsafe_execution_count: StrictInt = Field(ge=0)
    authorization_bypass_count: StrictInt = Field(ge=0)
    policy_bypass_count: StrictInt = Field(ge=0)
    duplicate_execution_count: StrictInt = Field(ge=0)

    unsafe_execution_rate: StrictFloat = Field(ge=0)
    authorization_bypass_rate: StrictFloat = Field(ge=0)
    policy_bypass_rate: StrictFloat = Field(ge=0)
    duplicate_execution_rate: StrictFloat = Field(ge=0)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    report_name: StrictStr = Field(min_length=1)
    version: StrictStr = Field(min_length=1)
    metrics: EvaluationMetrics
    results: list[EvaluationResult]
