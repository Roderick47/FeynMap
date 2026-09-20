import json
from pathlib import Path

import pytest

from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.repair_role_v1j import REPAIR_ROLES
from feynmap.judgment.repair_role_v1k import (
    REQUIRED_CHALLENGES,
    V1K_SCHEMA,
    run_experiment,
    validate_spec,
)

SPEC = Path(__file__).parents[1] / "experiments" / "repair_role_v1k.json"


def _spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


class TaskAwareOracleProvider:
    name = "task-aware-oracle"

    def __init__(self, spec):
        self.labels = {
            (str(task["description"]), str(candidate["id"])): dict(candidate["gold"])
            for task in spec["tasks"]
            for candidate in task["candidates"]
        }
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        description = str(state["task"]["description"])
        answers = {}
        for index, candidate in enumerate(state["grounded_context"]["candidates"]):
            gold = self.labels[(description, str(candidate["id"]))]
            role = str(gold["repair_role"])
            answers["relevance_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL,
                0.94 if gold["semantic_relevance"] else 0.06,
            )
            answers["role_%d" % index] = JudgmentAnswer(
                JudgmentKind.CHOICE,
                role,
                probabilities={
                    candidate_role: (0.91 if candidate_role == role else 0.03)
                    for candidate_role in REPAIR_ROLES
                },
            )
        return JudgmentResult(
            provider=self.name,
            model="oracle-v1",
            answers=answers,
            usage={"input_tokens": 100, "output_tokens": 20},
        )


def test_v1k_fixture_covers_adversarial_challenges_without_wikonomi():
    spec = _spec()
    validate_spec(spec)
    assert spec["schema"] == V1K_SCHEMA
    assert len(spec["tasks"]) == 8
    tags = {tag for task in spec["tasks"] for tag in task["challenge_tags"]}
    assert REQUIRED_CHALLENGES <= tags
    assert "wikonomi" not in json.dumps(spec).casefold()
    assert all(
        str(candidate["id"]).startswith("region_")
        for task in spec["tasks"]
        for candidate in task["candidates"]
    )


def test_v1k_task_conditioning_changes_gold_roles_for_identical_candidates():
    tasks = {
        task["id"]: task
        for task in _spec()["tasks"]
        if task.get("task_conditioning_group")
    }
    left = tasks["limit-comparison-repair"]
    right = tasks["limit-default-change"]
    left_roles = {
        item["id"]: item["gold"]["repair_role"] for item in left["candidates"]
    }
    right_roles = {
        item["id"]: item["gold"]["repair_role"] for item in right["candidates"]
    }
    assert set(left_roles) == set(right_roles)
    assert left_roles["region_01"] == "supporting_context"
    assert right_roles["region_01"] == "implementation_target"
    assert left_roles["region_02"] == "implementation_target"
    assert right_roles["region_02"] == "structural_bridge"


def test_v1k_scores_comparisons_uncertainty_and_multiple_targets():
    spec = _spec()
    provider = TaskAwareOracleProvider(spec)
    result = run_experiment(spec, provider)
    assert result["metrics"]["semantic_relevance_accuracy"] == 1.0
    assert result["metrics"]["repair_role_accuracy"] == 1.0
    assert result["diagnostics"]["repair_role_error_count"] == 0
    assert result["diagnostics"]["cross_axis_disagreement_count"] == 0
    assert (
        result["comparisons"]["task_conditioning"]["retry-limit-role-swap"][
            "changed_candidate_accuracy"
        ]
        == 1.0
    )
    assert (
        result["comparisons"]["order_invariance"]["projection-order"][
            "predicted_role_agreement"
        ]
        == 1.0
    )
    assert (
        result["comparisons"]["relationship_ablation"]["settlement-edges"][
            "predicted_role_agreement"
        ]
        == 1.0
    )
    assert result["target_ranking"]["implementation_target_mrr"] == 1.0
    assert result["target_ranking"]["implementation_target_recall@1"] < 1.0
    assert result["target_ranking"]["implementation_target_recall@3"] == 1.0
    assert result["stability"] == {"repetition_count": 1, "measured": False}
    control_ids = [
        state["task"]["id"]
        for state, _ in provider.calls
        if state["task"]["description"].startswith("Public export")
    ]
    assert control_ids == ["projection-order-control", "projection-order-control"]


def test_v1k_repeated_runs_report_stability_and_aggregate_usage():
    spec = _spec()
    provider = TaskAwareOracleProvider(spec)
    result = run_experiment(spec, provider, repetitions=2)
    assert result["stability"]["measured"] is True
    assert result["stability"]["mean_modal_role_agreement"] == 1.0
    assert result["stability"]["maximum_relevance_probability_span"] == 0.0
    assert result["stability"]["maximum_target_probability_span"] == 0.0
    assert result["usage"] == {"input_tokens": 1600, "output_tokens": 320}
    assert len(provider.calls) == 16


def test_v1k_validation_rejects_incomplete_comparison_groups():
    spec = _spec()
    spec["tasks"] = [
        task for task in spec["tasks"] if task["id"] != "order-control-reversed"
    ]
    with pytest.raises(ValueError, match="exactly two tasks"):
        validate_spec(spec)


def test_v1k_without_provider_only_validates_fixture():
    result = run_experiment(_spec())
    assert result["status"] == "fixture_validated"
    assert result["task_count"] == 8
    assert result["candidate_count"] == 35
    assert result["fixture_summary"]["v1j_prompts_frozen"] is True
    assert "metrics" not in result
