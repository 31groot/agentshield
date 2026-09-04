from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from engine.authorization import AuthorizationEngine
from engine.catalog import SQLiteCatalog
from engine.policy import DeterministicPolicyEngine
from models.authorization import AgentAuthorization
from models.catalog import CatalogProduct
from models.evaluation import (
    EvaluationCase,
    EvaluationMetrics,
    EvaluationOutcome,
    EvaluationReport,
    EvaluationResult,
)
from models.intent import IntentItem, IntentProposal
from models.policy import TransactionPolicy


class EvaluationRunner:
    """
    Deterministic AgentShield control-plane evaluator.

    Uses the real authorization engine, policy engine, and catalog.
    No LLM, Razorpay, or network dependency is used.
    """

    def __init__(self) -> None:
        self.authorization_engine = AuthorizationEngine()
        self.policy_engine = DeterministicPolicyEngine()

    @staticmethod
    def _intent(case: EvaluationCase) -> IntentProposal:
        return IntentProposal(
            user_id=case.user_id,
            agent_id=case.agent_id,
            intent_id=f"eval-{case.case_id}",
            raw_user_prompt=case.description,
            merchant_id=case.merchant_id,
            amount_paise=case.amount_paise,
            currency=case.currency,
            items=[
                IntentItem(
                    sku=case.sku,
                    quantity=case.quantity,
                )
            ],
            action_type="purchase",
            nonce=f"nonce-{case.case_id}",
        )

    @staticmethod
    def _authorization(case: EvaluationCase) -> AgentAuthorization:
        allowed_merchants = (
            [case.merchant_id]
            if case.authorization_merchant_allowed
            else ["different_merchant"]
        )

        allowed_skus = (
            [case.sku]
            if case.authorization_sku_allowed
            else ["different_sku"]
        )

        return AgentAuthorization(
            user_id=case.user_id,
            agent_id=case.agent_id,
            authorization_id=f"eval-auth-{case.case_id}",
            active=case.authorization_active,
            revoked=case.authorization_revoked,
            max_amount_paise=case.authorization_max_amount_paise,
            allowed_merchants=allowed_merchants,
            allowed_categories=[],
            allowed_skus=allowed_skus,
            max_quantity=case.authorization_max_quantity,
            currency=case.currency,
        )

    @staticmethod
    def _policy(case: EvaluationCase) -> TransactionPolicy:
        return TransactionPolicy(
            user_id=case.user_id,
            agent_id=case.agent_id,
            max_amount_paise=case.policy_max_amount_paise,
            min_amount_paise=case.policy_min_amount_paise,
            allowed_merchants=[],
            allowed_categories=(
                ["footwear"]
                if case.policy_category_allowed
                else ["electronics"]
            ),
            allowed_skus=[],
            max_quantity=case.policy_max_quantity,
            currency=case.currency,
            bank_rail_available=case.policy_bank_rail_available,
        )

    @staticmethod
    def _catalog(
        case: EvaluationCase,
        directory: Path,
    ) -> SQLiteCatalog:
        catalog = SQLiteCatalog(
            str(directory / f"{case.case_id}.catalog"),
        )

        if not case.catalog_exists:
            return catalog

        merchant_id = (
            case.merchant_id
            if case.catalog_merchant_matches
            else "different_merchant"
        )

        currency = (
            case.currency
            if case.catalog_currency_matches
            else "USD"
        )

        category = (
            "footwear"
            if case.catalog_category_matches
            else "different_category"
        )

        # The policy engine validates that the requested total equals:
        #
        #     catalog unit price * requested quantity
        #
        # Generate a coherent catalog price whenever the requested
        # amount is exactly divisible by quantity. This is especially
        # important for the valid quantity=2 boundary case.
        if case.amount_paise % case.quantity == 0:
            catalog_price_paise = (
                case.amount_paise // case.quantity
            )
        else:
            # Deliberately preserve an incoherent price when the
            # requested total cannot be represented as an integer
            # unit price. This allows the real policy engine to reject
            # an inconsistent transaction deterministically.
            catalog_price_paise = case.amount_paise

        catalog.create(
            CatalogProduct(
                merchant_id=merchant_id,
                sku=case.sku,
                name="Evaluation Shoe",
                category=category,
                price_paise=catalog_price_paise,
                currency=currency,
                stock=case.catalog_stock,
            )
        )

        return catalog

    @staticmethod
    def _reason_label(
        outcome: EvaluationOutcome,
    ) -> str:
        if outcome == EvaluationOutcome.ALLOW:
            return "APPROVED"

        return "BLOCKED"

    @staticmethod
    def _is_unsafe_execution(
        *,
        expected_outcome: EvaluationOutcome,
        razorpay_called: bool,
        execution_attempted: bool,
    ) -> bool:
        """
        An execution is unsafe when the system reached an execution
        attempt for a case that was expected to be blocked.

        The evaluator itself never calls Razorpay, so both execution
        flags remain false in this milestone. They are nevertheless
        persisted in the result model so later milestones can measure
        actual execution behavior without changing the report schema.
        """
        return (
            expected_outcome == EvaluationOutcome.BLOCK
            and (
                razorpay_called
                or execution_attempted
            )
        )

    def run_case(
        self,
        case: EvaluationCase,
        directory: Path,
    ) -> EvaluationResult:
        intent = self._intent(case)
        authorization = self._authorization(case)
        policy = self._policy(case)
        catalog = self._catalog(
            case,
            directory,
        )

        authorization_decision = self.authorization_engine.verify(
            intent,
            authorization,
        )

        authorization_allowed = (
            authorization_decision.allowed
        )

        policy_allowed = False
        actual_reason = authorization_decision.reason

        # Policy evaluation is intentionally unreachable when
        # authorization is rejected. This mirrors the production
        # execution invariant.
        if authorization_allowed:
            policy_decision = self.policy_engine.evaluate(
                intent,
                authorization,
                policy,
                catalog=catalog,
            )

            policy_allowed = policy_decision.allowed
            actual_reason = policy_decision.reason

        actual_outcome = (
            EvaluationOutcome.ALLOW
            if authorization_allowed and policy_allowed
            else EvaluationOutcome.BLOCK
        )

        # Execution is deliberately not part of this milestone.
        # The evaluator verifies the authorization/policy control
        # plane while keeping the Razorpay execution gate closed.
        razorpay_called = False
        execution_attempted = False

        passed = (
            actual_outcome == case.expected_outcome
        )

        unsafe_execution = self._is_unsafe_execution(
            expected_outcome=case.expected_outcome,
            razorpay_called=razorpay_called,
            execution_attempted=execution_attempted,
        )

        return EvaluationResult(
            case_id=case.case_id,
            category=case.category,
            expected_outcome=case.expected_outcome,
            actual_outcome=actual_outcome,
            expected_reason=self._reason_label(
                case.expected_outcome,
            ),
            actual_reason=actual_reason,
            authorization_allowed=authorization_allowed,
            policy_allowed=policy_allowed,
            razorpay_called=razorpay_called,
            execution_attempted=execution_attempted,
            unsafe_execution=unsafe_execution,
            final_state=(
                "APPROVED"
                if actual_outcome == EvaluationOutcome.ALLOW
                else "BLOCKED"
            ),
            passed=passed,
        )

    def run(
        self,
        cases: list[EvaluationCase],
    ) -> EvaluationReport:
        with TemporaryDirectory(
            prefix="agentshield-eval-"
        ) as temp:
            directory = Path(temp)

            results = [
                self.run_case(
                    case,
                    directory,
                )
                for case in cases
            ]

        total = len(results)

        passed = sum(
            result.passed
            for result in results
        )

        failed = total - passed

        unsafe_execution = sum(
            result.unsafe_execution
            for result in results
        )

        authorization_bypass = sum(
            result.expected_outcome == EvaluationOutcome.BLOCK
            and result.actual_outcome == EvaluationOutcome.ALLOW
            and result.category == "authorization"
            for result in results
        )

        policy_bypass = sum(
            result.expected_outcome == EvaluationOutcome.BLOCK
            and result.actual_outcome == EvaluationOutcome.ALLOW
            and result.category == "policy"
            for result in results
        )

        # Duplicate execution becomes measurable once the evaluator
        # exercises idempotency/execution paths in the next milestone.
        duplicate_execution = 0

        def rate(count: int) -> float:
            return count / total if total else 0.0

        metrics = EvaluationMetrics(
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            unsafe_execution_count=unsafe_execution,
            authorization_bypass_count=authorization_bypass,
            policy_bypass_count=policy_bypass,
            duplicate_execution_count=duplicate_execution,
            unsafe_execution_rate=rate(
                unsafe_execution,
            ),
            authorization_bypass_rate=rate(
                authorization_bypass,
            ),
            policy_bypass_rate=rate(
                policy_bypass,
            ),
            duplicate_execution_rate=rate(
                duplicate_execution,
            ),
        )

        return EvaluationReport(
            report_name=(
                "AgentShield deterministic "
                "control-plane evaluation"
            ),
            version="1.0",
            metrics=metrics,
            results=results,
        )
