import copy

from feynmap.judgment.context_ranker_v1f import _file_metrics
from feynmap.judgment.context_ranker_v1o import V1O_SCHEMA
from feynmap.judgment.context_ranker_v1r import V1R_SCHEMA, analyze_report
from feynmap.judgment.repair_role_v1j import REPAIR_ROLES


def _probabilities(selected):
    return {role: (0.91 if role == selected else 0.03) for role in REPAIR_ROLES}


def _candidate(candidate_id, path, relevance, role):
    probabilities = _probabilities(role)
    return {
        "candidate_id": candidate_id,
        "candidate": candidate_id,
        "path": path,
        "semantic_relevance_probability": relevance,
        "predicted_repair_role": role,
        "repair_role_probabilities": probabilities,
        "coherent_repair_role": role,
        "coherent_role_probabilities": probabilities,
        "eligible": role != "incidental_context",
    }


def _report():
    context_order = ["root.py", "bridge.py", "target.py", "noise.py"]
    gold = {"target.py"}
    context_metrics = _file_metrics(
        context_order,
        gold,
        ks=(1, 3, 5, 10),
        path_backed_files={"target.py"},
    )
    candidates = [
        _candidate("bridge", "bridge.py", 0.98, "structural_bridge"),
        _candidate("target", "target.py", 0.72, "implementation_target"),
        _candidate("noise", "noise.py", 0.10, "incidental_context"),
    ]
    return {
        "schema": V1O_SCHEMA,
        "status": "judged",
        "adaptive_summary": {
            "reranked": context_metrics,
            "role_shadow": {"metrics": context_metrics},
        },
        "tasks": [
            {
                "id": "fixture-task",
                "gold_existing_files": ["target.py"],
                "adaptive": {
                    "reranked_file_order": context_order,
                    "reranked": context_metrics,
                    "path_backed_gold_files": ["target.py"],
                    "role_shadow": {
                        "metrics": context_metrics,
                        "candidates": candidates,
                    },
                },
            }
        ],
    }


def test_context_order_and_metrics_are_preserved_exactly():
    result = analyze_report(_report())
    task = result["tasks"][0]

    assert result["schema"] == V1R_SCHEMA
    assert result["provider_calls_made"] == 0
    assert result["production_policy_changed"] is False
    assert result["all_context_orders_unchanged"] is True
    assert result["all_context_metrics_unchanged"] is True
    assert task["context_file_order"] == [
        "root.py",
        "bridge.py",
        "target.py",
        "noise.py",
    ]
    assert task["context_metrics"] == task["verified_context_metrics"]
    assert set(task["context_metric_deltas"].values()) == {0.0}


def test_roles_produce_separate_target_guidance_without_filtering():
    result = analyze_report(_report())
    task = result["tasks"][0]

    assert result["all_candidates_retained"] is True
    assert task["candidate_retention_ratio"] == 1.0
    assert task["edit_target_candidate_order"][0] == "target"
    assert task["edit_target_file_order"][0] == "target.py"
    assert task["role_lanes"]["incidental_context"] == ["noise"]
    assert task["changed_file_proxy_metrics"]["reciprocal_rank"] == 1.0
    assert result["policy"]["context_filtering_by_role"] is False
    assert result["policy"]["changed_files_are_exact_role_labels"] is False


def test_output_is_invariant_to_role_candidate_input_order():
    forward = analyze_report(_report())
    reversed_report = copy.deepcopy(_report())
    reversed_report["tasks"][0]["adaptive"]["role_shadow"]["candidates"].reverse()
    reversed_result = analyze_report(reversed_report)

    assert forward["tasks"] == reversed_result["tasks"]
    assert forward["order_invariant"] is True


def test_annotations_do_not_expose_historical_gold():
    annotation = analyze_report(_report())["tasks"][0]["role_annotations"][0]

    assert "gold_existing_files" not in annotation
    assert "changed_file" not in annotation
    assert set(annotation) == {
        "candidate_id",
        "candidate",
        "path",
        "semantic_relevance_probability",
        "coherent_repair_role",
        "coherent_role_probabilities",
    }
