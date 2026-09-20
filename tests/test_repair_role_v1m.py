import copy
import json

import pytest

from feynmap.judgment.repair_role_v1m import (
    V1M_SCHEMA,
    coherent_role_distribution,
    load_report,
    run_analysis,
    validate_report,
)


def _row(
    candidate_id,
    relevance,
    predicted_role,
    probabilities,
    primary,
    acceptable=None,
):
    return {
        "candidate_id": candidate_id,
        "region": {"path": "unit/sample.src", "start_line": 1, "end_line": 5},
        "semantic_relevance_probability": relevance,
        "predicted_repair_role": predicted_role,
        "repair_role_probabilities": probabilities,
        "primary_label": primary,
        "acceptable_labels": acceptable or [primary],
    }


def _report():
    target = {
        "semantic_relevance": True,
        "repair_role": "implementation_target",
    }
    incidental = {
        "semantic_relevance": False,
        "repair_role": "incidental_context",
    }
    supporting = {
        "semantic_relevance": True,
        "repair_role": "supporting_context",
    }
    return {
        "schema": "feynmap.repair_role_v1l.v1",
        "status": "judged",
        "tasks": [
            {
                "id": "coherence-control",
                "candidates": [
                    _row(
                        "region_1",
                        0.95,
                        "implementation_target",
                        {
                            "implementation_target": 0.9,
                            "structural_bridge": 0.05,
                            "supporting_context": 0.03,
                            "incidental_context": 0.02,
                        },
                        target,
                    ),
                    _row(
                        "region_2",
                        0.42,
                        "supporting_context",
                        {
                            "implementation_target": 0.01,
                            "structural_bridge": 0.16,
                            "supporting_context": 0.55,
                            "incidental_context": 0.28,
                        },
                        incidental,
                        [incidental, supporting],
                    ),
                    _row(
                        "region_3",
                        0.1,
                        "incidental_context",
                        {
                            "implementation_target": 0.01,
                            "structural_bridge": 0.05,
                            "supporting_context": 0.09,
                            "incidental_context": 0.85,
                        },
                        incidental,
                    ),
                ],
            }
        ],
    }


def test_v1m_repairs_cross_axis_label_without_changing_provider_output():
    report = _report()
    original = copy.deepcopy(report)
    result = run_analysis(report)
    assert result["schema"] == V1M_SCHEMA
    assert result["provider_calls_made"] == 0
    assert result["metrics"]["raw_primary_joint_accuracy"] == pytest.approx(2 / 3)
    assert result["metrics"]["coherent_primary_joint_accuracy"] == pytest.approx(2 / 3)
    assert result["metrics"]["raw_acceptable_joint_accuracy"] == pytest.approx(2 / 3)
    assert result["metrics"]["coherent_acceptable_joint_accuracy"] == 1.0
    assert result["metrics"]["cross_axis_disagreement_count"] == 1
    assert result["metrics"]["coherent_role_changed_count"] == 0
    assert result["metrics"]["coherent_relevance_changed_count"] == 1
    assert result["metrics"]["repaired_unacceptable_count"] == 1
    assert result["metrics"]["introduced_regression_count"] == 0
    assert len(result["coherence_cases"]) == 1
    case = result["coherence_cases"][0]
    assert case["raw_label"] == {
        "semantic_relevance": False,
        "repair_role": "supporting_context",
    }
    assert case["coherent_label"] == {
        "semantic_relevance": True,
        "repair_role": "supporting_context",
    }
    assert result["remaining_unacceptable_cases"] == []
    assert report == original


def test_v1m_coherent_distribution_is_normalized_and_parameter_free():
    row = _report()["tasks"][0]["candidates"][1]
    distribution = coherent_role_distribution(row)
    assert sum(distribution.values()) == pytest.approx(1.0)
    assert distribution["supporting_context"] == pytest.approx(0.231 / 0.4648)
    assert distribution["incidental_context"] == pytest.approx(0.1624 / 0.4648)


def test_v1m_preserves_target_ranking():
    result = run_analysis(_report())
    ranking = result["target_ranking"]
    assert ranking["implementation_target_mrr"] == 1.0
    assert ranking["implementation_target_recall@1"] == 1.0
    assert ranking["implementation_target_recall@3"] == 1.0
    assert ranking["task_orders"]["coherence-control"][0] == "region_1"


def test_v1m_rejects_unjudged_or_invalid_reports():
    report = _report()
    report["status"] = "fixture_validated"
    with pytest.raises(ValueError, match="judged repair-role v1L"):
        validate_report(report)

    report = _report()
    report["tasks"][0]["candidates"][0]["semantic_relevance_probability"] = 1.2
    with pytest.raises(ValueError, match="invalid relevance probability"):
        validate_report(report)


def test_v1m_loads_windows_powershell_utf16_json(tmp_path):
    path = tmp_path / "v1l-result.json"
    path.write_text(json.dumps(_report()), encoding="utf-16")
    assert load_report(path) == _report()
