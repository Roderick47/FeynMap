import copy
import json
from pathlib import Path

import pytest

from feynmap.judgment.repair_role_v1j import REPAIR_ROLES
from feynmap.judgment.repair_role_v1n import (
    V1N_SCHEMA,
    assemble_under_budget,
    role_aware_order,
    run_experiment,
    validate_spec,
)

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "experiments" / "repair_role_v1l.json"
SPEC = ROOT / "experiments" / "repair_role_v1n.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _judged_report(fixture):
    tasks = []
    for task in fixture["tasks"]:
        candidates = []
        for candidate in reversed(task["candidates"]):
            primary = candidate["adjudication"]["primary"]
            role = primary["repair_role"]
            candidates.append(
                {
                    "candidate_id": candidate["id"],
                    "region": candidate["region"],
                    "semantic_relevance_probability": (
                        0.9 if primary["semantic_relevance"] else 0.1
                    ),
                    "predicted_repair_role": role,
                    "repair_role_probabilities": {
                        item: (0.91 if item == role else 0.03) for item in REPAIR_ROLES
                    },
                    "primary_label": dict(primary),
                    "acceptable_labels": [
                        dict(label)
                        for label in candidate["adjudication"]["acceptable_labels"]
                    ],
                }
            )
        tasks.append({"id": task["id"], "candidates": candidates})
    return {
        "schema": "feynmap.repair_role_v1l.v1",
        "status": "judged",
        "tasks": tasks,
    }


def _policy_candidates():
    roles = {
        "target": "implementation_target",
        "bridge": "structural_bridge",
        "support": "supporting_context",
        "noise": "incidental_context",
    }
    rows = []
    for candidate_id, role in roles.items():
        rows.append(
            {
                "candidate_id": candidate_id,
                "coherent_role_probabilities": {
                    item: (0.91 if item == role else 0.03) for item in REPAIR_ROLES
                },
            }
        )
    return rows


def test_v1n_policy_is_order_invariant_and_preserves_role_diversity():
    candidates = _policy_candidates()
    original = copy.deepcopy(candidates)
    expected = ["target", "support", "bridge", "noise"]
    assert role_aware_order(candidates) == expected
    assert role_aware_order(list(reversed(candidates))) == expected
    assert candidates == original


def test_v1n_budget_assembly_is_deterministic_and_skips_items_that_do_not_fit():
    result = assemble_under_budget(
        ["target", "support", "bridge", "noise"],
        {"target": 7, "support": 6, "bridge": 3, "noise": 2},
        12,
    )
    assert result["selected"] == ["target", "bridge", "noise"]
    assert result["used_tokens"] == 12
    assert result["remaining_tokens"] == 0
    filtered = assemble_under_budget(
        ["target", "support", "bridge", "noise"],
        {"target": 7, "support": 6, "bridge": 3, "noise": 2},
        12,
        eligible_ids=["target", "support", "bridge"],
    )
    assert filtered["selected"] == ["target", "bridge"]
    assert filtered["remaining_tokens"] == 2
    with pytest.raises(ValueError, match="positive"):
        assemble_under_budget(["target"], {"target": 1}, 0)


def test_v1n_shadow_experiment_uses_no_provider_or_gold_for_ordering():
    fixture = _fixture()
    report = _judged_report(fixture)
    result = run_experiment(report, fixture, _spec())
    assert result["schema"] == V1N_SCHEMA
    assert result["provider_calls_made"] == 0
    assert result["production_policy_changed"] is False
    assert result["order_invariant"] is True
    assert result["task_count"] == 5
    assert result["policy"]["gold_labels_used_for_selection"] is False
    assert all(task["role_aware_order"][0].endswith("1") for task in result["tasks"])
    assert all(
        budget["role_aware"]["implementation_target_hit"]
        for task in result["tasks"]
        for budget in task["budgets"]
    )

    relabeled = copy.deepcopy(report)
    for task in relabeled["tasks"]:
        labels = [candidate["primary_label"] for candidate in task["candidates"]]
        for candidate, label in zip(task["candidates"], labels[1:] + labels[:1]):
            candidate["primary_label"] = label
    relabeled_result = run_experiment(relabeled, fixture, _spec())
    assert [task["role_aware_order"] for task in result["tasks"]] == [
        task["role_aware_order"] for task in relabeled_result["tasks"]
    ]


def test_v1n_summary_reports_role_and_relevance_policy_comparison():
    fixture = _fixture()
    result = run_experiment(_judged_report(fixture), fixture, _spec())
    assert list(result["summary"]) == [
        "fraction_0.25",
        "fraction_0.5",
        "fraction_0.75",
        "fraction_1",
    ]
    full = result["summary"]["fraction_1"]
    for policy in ("role_aware", "relevance_only"):
        assert full[policy]["implementation_target_recall"] == 1.0
        assert full[policy]["semantic_relevance_recall"] == 1.0
        assert full[policy]["context_role_coverage"] == 1.0
        assert full[policy]["acceptable_context_role_coverage"] == 1.0
        assert full[policy]["unacceptable_selection_ratio"] == 0.0


def test_v1n_validates_budget_and_fixture_alignment():
    validate_spec(_spec())
    invalid = _spec()
    invalid["budget_fractions"] = [0.5, 0.25]
    with pytest.raises(ValueError, match="sorted"):
        validate_spec(invalid)

    fixture = _fixture()
    report = _judged_report(fixture)
    report["tasks"].pop()
    with pytest.raises(ValueError, match="task ids must match"):
        run_experiment(report, fixture, _spec())
