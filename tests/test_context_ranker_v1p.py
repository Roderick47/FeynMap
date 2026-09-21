import json

import pytest

from feynmap.judgment.context_ranker_v1o import V1O_SCHEMA
from feynmap.judgment.context_ranker_v1p import (
    SAFETY_METRICS,
    V1P_SCHEMA,
    analyze_report,
    load_report,
)


def _metrics(value, missing=None):
    result = {metric: value for metric in SAFETY_METRICS}
    result["missing_gold_files"] = missing
    return result


def _report(shadow_value=0.8, shadow_missing=None, eligible=False):
    relevance = _metrics(0.8)
    shadow_metrics = _metrics(shadow_value, shadow_missing)
    return {
        "schema": V1O_SCHEMA,
        "status": "judged",
        "adaptive_summary": {
            "reranked": relevance,
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "provider_elapsed_seconds": 4.0,
            "combined_usage": {"input_tokens": 250, "output_tokens": 40},
            "role_shadow": {
                "metrics": shadow_metrics,
                "usage": {"input_tokens": 150, "output_tokens": 30},
                "provider_elapsed_seconds": 2.0,
            },
        },
        "tasks": [
            {
                "id": "fixture-task",
                "gold_existing_files": ["changed.py"],
                "adaptive": {
                    "reranked": relevance,
                    "role_shadow": {
                        "metrics": shadow_metrics,
                        "candidates": [
                            {
                                "candidate_id": "region:changed",
                                "candidate": "changed_region",
                                "path": "changed.py",
                                "eligible": eligible,
                                "semantic_relevance_probability": 0.2,
                                "predicted_repair_role": "incidental_context",
                                "coherent_repair_role": "incidental_context",
                                "coherent_role_probabilities": {
                                    "incidental_context": 0.9
                                },
                            }
                        ],
                    },
                },
            }
        ],
    }


def test_gate_rejects_metric_regression_and_new_missing_file():
    result = analyze_report(_report(0.4, ["changed.py"]))

    assert result["schema"] == V1P_SCHEMA
    assert result["provider_calls_made"] == 0
    assert result["production_policy_changed"] is False
    assert result["promotion_ready"] is False
    assert result["decision"] == "reject_hard_incidental_filter"
    assert result["summary"]["regressed_task_count"] == 1
    assert result["summary"]["new_missing_gold_files"] == ["changed.py"]
    assert result["summary"]["excluded_changed_file_candidate_count"] == 1


def test_gate_passes_equal_metrics_without_new_missing_file():
    result = analyze_report(_report(0.8, None, eligible=True))

    assert result["promotion_ready"] is True
    assert result["decision"] == "eligible_for_explicit_review"
    assert result["summary"]["safe_task_count"] == 1
    assert result["summary"]["aggregate_regressed_metrics"] == []


def test_usage_ratios_are_reported_without_cost_thresholds():
    result = analyze_report(_report(0.8, None, eligible=True))
    usage = result["summary"]["usage"]

    assert usage["ratios"]["input_tokens"]["role_to_relevance"] == 1.5
    assert usage["ratios"]["output_tokens"]["combined_to_relevance"] == 4.0
    assert usage["role_elapsed_to_relevance"] == 0.5
    assert result["policy"]["tuned_thresholds"] is False


def test_load_report_accepts_utf16_and_validation_rejects_wrong_schema(tmp_path):
    path = tmp_path / "v1o.json"
    path.write_text(json.dumps(_report()), encoding="utf-16")
    loaded = load_report(path)
    assert loaded["schema"] == V1O_SCHEMA

    loaded["schema"] = "wrong"
    with pytest.raises(ValueError, match="judged context-ranker v1O"):
        analyze_report(loaded)
