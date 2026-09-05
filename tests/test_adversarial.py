from __future__ import annotations

import asyncio

from evaluation.adversarial_runner import (
    run_adversarial_suite,
)
from evaluation.adversarial_scenarios import (
    build_adversarial_scenarios,
)


def test_adversarial_suite_has_at_least_15_cases():
    scenarios = build_adversarial_scenarios()

    assert len(scenarios) >= 15


def test_adversarial_scenario_ids_are_unique():
    scenarios = build_adversarial_scenarios()

    ids = [
        scenario.scenario_id
        for scenario in scenarios
    ]

    assert len(ids) == len(set(ids))


def test_adversarial_suite_blocks_unsafe_execution():
    report = asyncio.run(
        run_adversarial_suite(
            build_adversarial_scenarios(),
        )
    )

    assert (
        report.metrics.unsafe_execution_rate
        == 0.0
    )

    assert (
        report.metrics.execution_after_block_rate
        == 0.0
    )


def test_adversarial_suite_has_no_bypass():
    report = asyncio.run(
        run_adversarial_suite(
            build_adversarial_scenarios(),
        )
    )

    assert (
        report.metrics.authorization_bypass_rate
        == 0.0
    )

    assert (
        report.metrics.policy_bypass_rate
        == 0.0
    )
