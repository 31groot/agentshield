from __future__ import annotations

import json
from pathlib import Path

from evaluation import (
    EvaluationRunner,
    build_evaluation_cases,
)


def main() -> int:
    cases = build_evaluation_cases()
    report = EvaluationRunner().run(cases)

    output_path = Path("reports/evaluation.json")
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(f"Evaluation cases: {report.metrics.total_cases}")
    print(f"Passed: {report.metrics.passed_cases}")
    print(f"Failed: {report.metrics.failed_cases}")
    print(
        "Unsafe execution rate: "
        f"{report.metrics.unsafe_execution_rate:.4f}"
    )
    print(
        "Authorization bypass rate: "
        f"{report.metrics.authorization_bypass_rate:.4f}"
    )
    print(
        "Policy bypass rate: "
        f"{report.metrics.policy_bypass_rate:.4f}"
    )
    print(f"Report: {output_path}")

    return 0 if report.metrics.failed_cases == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
