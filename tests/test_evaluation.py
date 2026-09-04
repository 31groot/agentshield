from __future__ import annotations

import json
from pathlib import Path

from evaluation import (
    EvaluationRunner,
    build_evaluation_cases,
)
from models.evaluation import EvaluationOutcome


def test_evaluation_suite_contains_at_least_60_cases():
    cases = build_evaluation_cases()

    assert len(cases) >= 60


def test_evaluation_case_ids_are_unique():
    cases = build_evaluation_cases()

    ids = [case.case_id for case in cases]

    assert len(ids) == len(set(ids))


def test_evaluation_models_are_strict():
    cases = build_evaluation_cases()

    assert cases

    case = cases[0]

    assert case.expected_outcome in {
        EvaluationOutcome.ALLOW,
        EvaluationOutcome.BLOCK,
    }


def test_deterministic_evaluation_has_no_unsafe_execution():
    report = EvaluationRunner().run(
        build_evaluation_cases(),
    )

    assert report.metrics.unsafe_execution_count == 0
    assert report.metrics.unsafe_execution_rate == 0.0


def test_evaluation_report_is_json_serializable(tmp_path: Path):
    report = EvaluationRunner().run(
        build_evaluation_cases(),
    )

    path = tmp_path / "evaluation.json"

    path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = json.loads(
        path.read_text(encoding="utf-8"),
    )

    assert loaded["metrics"]["total_cases"] >= 60
    assert loaded["metrics"]["unsafe_execution_rate"] == 0.0
