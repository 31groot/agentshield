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


class AdversarialOutcome(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class AdversarialScenario(BaseModel):
    """
    One hostile or adversarial payment proposal.

    The scenario describes what the attacker/LLM is attempting to do.
    It does not grant any financial authority to the scenario itself.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    scenario_id: StrictStr = Field(min_length=1)
    category: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)

    user_message: StrictStr = Field(min_length=1)

    proposed_amount_paise: StrictInt = Field(gt=0)
    proposed_merchant_id: StrictStr = Field(min_length=1)
    proposed_sku: StrictStr = Field(min_length=1)
    proposed_quantity: StrictInt = Field(ge=1)
    proposed_currency: StrictStr = Field(
        min_length=3,
        max_length=3,
    )

    expected_outcome: AdversarialOutcome

    expect_runnable: StrictBool = False
    expect_identity_rejection: StrictBool = False
    expect_authorization_rejection: StrictBool = False
    expect_policy_rejection: StrictBool = False


class AdversarialResult(BaseModel):
    """
    Observed result from the real AgentShield orchestrator.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    scenario_id: StrictStr = Field(min_length=1)
    category: StrictStr = Field(min_length=1)

    expected_outcome: AdversarialOutcome
    actual_outcome: AdversarialOutcome

    passed: StrictBool

    exception_type: StrictStr | None = None
    reason: StrictStr | None = None

    authorization_rejected: StrictBool
    policy_rejected: StrictBool
    identity_rejected: StrictBool

    razorpay_called: StrictBool
    execution_attempted: StrictBool

    final_state: StrictStr | None = None

    unsafe_execution: StrictBool
    execution_after_block: StrictBool


class AdversarialMetrics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    total_cases: StrictInt = Field(ge=0)
    passed_cases: StrictInt = Field(ge=0)
    failed_cases: StrictInt = Field(ge=0)

    unsafe_execution_count: StrictInt = Field(ge=0)
    authorization_bypass_count: StrictInt = Field(ge=0)
    policy_bypass_count: StrictInt = Field(ge=0)
    execution_after_block_count: StrictInt = Field(ge=0)

    unsafe_execution_rate: StrictFloat = Field(ge=0)
    authorization_bypass_rate: StrictFloat = Field(ge=0)
    policy_bypass_rate: StrictFloat = Field(ge=0)
    execution_after_block_rate: StrictFloat = Field(ge=0)


class AdversarialReport(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    report_name: StrictStr = Field(min_length=1)
    version: StrictStr = Field(min_length=1)

    metrics: AdversarialMetrics
    results: list[AdversarialResult]
