import copy

from feynmap.judgment.repair_role_v1j import REPAIR_ROLES
from feynmap.judgment.repair_role_v1l import V1L_SCHEMA
from feynmap.judgment.repair_role_v1q import V1Q_SCHEMA, analyze_report


def _probabilities(selected):
    return {role: (0.91 if role == selected else 0.03) for role in REPAIR_ROLES}


def _candidate(candidate_id, relevance, predicted, gold):
    return {
        "candidate_id": candidate_id,
        "task_id": "fixture-task",
        "region": {"path": "fixture.src", "start_line": 1, "end_line": 2},
        "semantic_relevance_probability": relevance,
        "predicted_repair_role": predicted,
        "repair_role_probabilities": _probabilities(predicted),
        "primary_label": {"semantic_relevance": True, "repair_role": gold},
        "acceptable_labels": [{"semantic_relevance": True, "repair_role": gold}],
    }


def _report():
    return {
        "schema": V1L_SCHEMA,
        "status": "judged",
        "tasks": [
            {
                "id": "fixture-task",
                "candidates": [
                    _candidate(
                        "bridge", 0.98, "structural_bridge", "structural_bridge"
                    ),
                    _candidate(
                        "target", 0.72, "implementation_target", "implementation_target"
                    ),
                    _candidate(
                        "support", 0.81, "supporting_context", "supporting_context"
                    ),
                    _candidate(
                        "noise", 0.12, "incidental_context", "incidental_context"
                    ),
                ],
            }
        ],
    }


def test_context_order_is_relevance_owned_and_retains_every_candidate():
    result = analyze_report(_report())
    task = result["tasks"][0]

    assert result["schema"] == V1Q_SCHEMA
    assert result["provider_calls_made"] == 0
    assert result["production_policy_changed"] is False
    assert task["context_order"] == ["bridge", "support", "target", "noise"]
    assert task["retained_candidate_ids"] == task["context_order"]
    assert task["all_candidates_retained"] is True
    assert task["candidate_retention_ratio"] == 1.0


def test_roles_are_a_separate_target_order_and_explanatory_lanes():
    result = analyze_report(_report())
    task = result["tasks"][0]

    assert task["edit_target_order"][0] == "target"
    assert task["role_lanes"]["implementation_target"] == ["target"]
    assert task["role_lanes"]["structural_bridge"] == ["bridge"]
    assert task["implementation_target_metrics"]["reciprocal_rank"] == 1.0
    assert result["summary"]["implementation_target_task_hit_rate@1"] == 1.0
    assert result["policy"]["context_filtering_by_role"] is False
    assert result["policy"]["context_reordering_by_role"] is False


def test_dual_channel_output_is_invariant_to_input_order():
    forward = analyze_report(_report())
    reversed_report = copy.deepcopy(_report())
    reversed_report["tasks"][0]["candidates"].reverse()
    reversed_result = analyze_report(reversed_report)

    assert forward["tasks"] == reversed_result["tasks"]
    assert forward["order_invariant"] is True


def test_role_annotations_exclude_evaluation_labels():
    annotation = analyze_report(_report())["tasks"][0]["role_annotations"][0]

    assert "primary_label" not in annotation
    assert "acceptable_labels" not in annotation
    assert "gold_repair_role" not in annotation
    assert set(annotation) == {
        "candidate_id",
        "region",
        "semantic_relevance_probability",
        "coherent_repair_role",
        "coherent_role_probabilities",
    }
