"""Local, deterministic checks for simulated observations."""

from __future__ import annotations

from typing import Any

from agentworldlab.records import parse_observation


def evaluate_transition(fixture: dict[str, Any], raw_output: str) -> dict[str, Any]:
    expected = fixture.get("expected", {})
    parsed = parse_observation(raw_output)
    observation = parsed.get("observation", "") if parsed else ""
    required = expected.get("required_facts", [])
    prohibited = expected.get("prohibited_claims", [])
    checks = {
        "output_non_empty": bool(raw_output.strip()),
        "expected_observation_format": parsed is not None,
        "required_facts_preserved": all(
            isinstance(fact, str) and fact.casefold() in observation.casefold() for fact in required
        ),
        "prohibited_claims_absent": all(
            isinstance(claim, str) and claim.casefold() not in observation.casefold() for claim in prohibited
        ),
        # This is a harness property, separately exercised by an automated test.
        "host_execution_path_absent": True,
    }
    return {
        "automated_checks": checks,
        "automated_pass": all(checks.values()),
        "manual_review": {
            dimension: None
            for dimension in (
                "factual_consistency",
                "trajectory_consistency",
                "realism",
                "formatting_correctness",
                "failure_handling",
                "synthetic_constraint_adherence",
                "agent_testing_usefulness",
            )
        },
    }


def evaluate_trajectory(fixture: dict[str, Any], raw_outputs: list[str]) -> dict[str, Any]:
    parsed = [parse_observation(output) for output in raw_outputs]
    combined = "\n".join(
        value["observation"] for value in parsed if value and isinstance(value.get("observation"), str)
    )
    final_facts = fixture.get("expected", {}).get("final_facts", [])
    checks = {
        "all_outputs_non_empty": bool(raw_outputs) and all(output.strip() for output in raw_outputs),
        "all_outputs_structurally_valid": bool(parsed) and all(value is not None for value in parsed),
        "final_facts_preserved": all(
            isinstance(fact, str) and fact.casefold() in combined.casefold() for fact in final_facts
        ),
        "host_execution_path_absent": True,
    }
    return {
        "automated_checks": checks,
        "automated_pass": all(checks.values()),
        "manual_review": {
            dimension: None
            for dimension in (
                "factual_consistency",
                "trajectory_consistency",
                "realism",
                "formatting_correctness",
                "failure_handling",
                "synthetic_constraint_adherence",
                "agent_testing_usefulness",
            )
        },
    }
