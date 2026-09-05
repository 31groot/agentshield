from __future__ import annotations

import asyncio
import json
from pathlib import Path

from evaluation.adversarial_runner import (
    run_adversarial_suite,
)
from evaluation.adversarial_scenarios import (
    build_adversarial_scenarios,
)


async def main() -> int:
    scenarios = build_adversarial_scenarios()

    report = await run_adversarial_suite(
        scenarios,
    )

    output_path = Path(
        "reports/adversarial.json"
    )

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

    print(
        f"Adversarial cases: "
        f"{report.metrics.total_cases}"
    )
    print(
        f"Passed: "
        f"{report.metrics.passed_cases}"
    )
    print(
        f"Failed: "
        f"{report.metrics.failed_cases}"
    )
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
    print(
        "Execution-after-block rate: "
        f"{report.metrics.execution_after_block_rate:.4f}"
    )
    print(
        f"Report: {output_path}"
    )

    return (
        0
        if report.metrics.failed_cases == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
