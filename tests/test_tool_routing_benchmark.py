import json

import pytest

from feynmap.tool_routing_benchmark import (
    BENCHMARK_SCHEMA,
    run_benchmark,
    validate_dataset,
)


def _fixture():
    with open("experiments/tool_routing_s5.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_s5_benchmark_measures_ranking_delivery_and_schema_reduction():
    result = run_benchmark(_fixture())
    summary = result["summary"]

    assert result["schema"] == BENCHMARK_SCHEMA
    assert result["tool_count"] == 13
    assert result["task_count"] == 15
    assert result["positive_task_count"] == 14
    assert result["unmatched_task_count"] == 1
    assert summary["top1_accuracy"] == 1.0
    assert summary["mean_reciprocal_rank"] == 1.0
    assert summary["mean_recall@1"] == 1.0
    assert summary["unmatched_accuracy"] == 1.0
    assert 0.0 < summary["mean_delivery_recall"] < 1.0
    assert summary["schema_token_reduction_ratio"] > 0.5
    assert summary["total_delivered_schema_tokens"] < summary["total_full_catalog_schema_tokens"]
    assert summary["schema_tokens_avoided"] == (
        summary["total_full_catalog_schema_tokens"]
        - summary["total_delivered_schema_tokens"]
    )


def test_ambiguous_and_unmatched_tasks_are_reported_separately():
    result = run_benchmark(_fixture())
    rows = {row["id"]: row for row in result["tasks"]}

    ambiguous = rows["ambiguous-symbol-evidence"]
    assert ambiguous["ranked_tools"][0] == "explain_evidence"
    assert ambiguous["top1_correct"] is True
    assert ambiguous["route_sufficient"] is False
    assert ambiguous["route_reason"] == "ambiguous_margin"
    assert ambiguous["delivered_tools"] == []
    assert ambiguous["delivery_recall"] == 0.0

    unmatched = rows["unmatched-request"]
    assert unmatched["ranked_tools"] == []
    assert unmatched["delivered_tools"] == []
    assert unmatched["correct_abstention"] is True
    assert unmatched["reciprocal_rank"] is None
    assert unmatched["delivered_schema_tokens"] == 0


def test_schema_token_baseline_uses_the_same_full_catalog_for_every_task():
    result = run_benchmark(_fixture())
    baseline = result["summary"]["full_catalog_schema_tokens_per_task"]

    assert baseline > 0
    assert {row["full_schema_tokens"] for row in result["tasks"]} == {baseline}
    assert result["summary"]["total_full_catalog_schema_tokens"] == (
        baseline * result["task_count"]
    )
    assert all(
        row["delivered_schema_tokens"] <= row["full_schema_tokens"]
        for row in result["tasks"]
    )


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda data: data.update(schema="wrong"), "unsupported"),
        (lambda data: data.update(tasks=[]), "non-empty"),
        (lambda data: data["tasks"][0].update(id=""), "non-empty id"),
        (lambda data: data["tasks"][0].update(query=""), "non-empty query"),
        (lambda data: data["tasks"][0].update(expected_tools="trace_path"), "must be a list"),
        (lambda data: data["tasks"][0].update(expected_tools=["invented"]), "unknown"),
        (lambda data: data["tasks"][1].update(id=data["tasks"][0]["id"]), "unique"),
    ],
)
def test_dataset_validation_rejects_invalid_or_ungrounded_labels(mutation, message):
    dataset = _fixture()
    mutation(dataset)
    with pytest.raises(ValueError, match=message):
        validate_dataset(
            dataset,
            tool_names=(
                "repository_summary", "get_symbol", "find_callers", "find_dependencies",
                "change_impact", "validate_claim", "trace_path", "find_integrations",
                "explain_evidence", "unresolved", "context_bundle", "minimal_context",
                "semantic_diff",
            ),
        )


def test_dataset_requires_positive_and_unmatched_cases():
    dataset = _fixture()
    dataset["tasks"] = [task for task in dataset["tasks"] if task["expected_tools"]]
    with pytest.raises(ValueError, match="unmatched"):
        validate_dataset(dataset, tool_names=tuple(
            name for task in dataset["tasks"] for name in task["expected_tools"]
        ))

    dataset = _fixture()
    dataset["tasks"] = [dataset["tasks"][-1]]
    with pytest.raises(ValueError, match="positive"):
        validate_dataset(dataset, tool_names=())


def test_invalid_benchmark_settings_are_rejected():
    dataset = _fixture()
    dataset["settings"]["limit"] = 0
    with pytest.raises(ValueError, match="limit must be positive"):
        run_benchmark(dataset)
