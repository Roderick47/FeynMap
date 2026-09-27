import json

import pytest

from feynmap.performance_profile import (
    PROFILE_SCHEMA,
    profile_callable,
    run_profile,
    validate_spec,
)


def _activation_dataset():
    return {
        "schema": "feynmap.sparse_activation_benchmark.v1",
        "name": "tiny profile activation",
        "analysis": {"language": "python", "framework": "none"},
        "tasks": [
            {
                "id": "helper",
                "mode": "node",
                "root": "app.run",
                "query": "Find helper dependencies",
                "essential_symbols": ["app.helper"],
            }
        ],
    }


def _tool_dataset():
    return {
        "schema": "feynmap.tool_routing_benchmark.v1",
        "name": "tiny profile routing",
        "tasks": [
            {
                "id": "callers",
                "query": "Find incoming callers and invocations for this symbol.",
                "expected_tools": ["find_callers"],
            },
            {
                "id": "unmatched",
                "query": "quantum banana orchestra",
                "expected_tools": [],
            },
        ],
    }


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_profile_callable_reports_serializable_sorted_hotspots(tmp_path):
    def action():
        return sum(value * value for value in range(100))

    report, result = profile_callable("tiny", action, source_root=tmp_path, top_n=3)

    assert result == 328350
    assert report["name"] == "tiny"
    assert report["elapsed_ms"] >= 0
    assert report["total_calls"] >= report["primitive_calls"]
    assert len(report["top_cumulative_functions"]) <= 3
    cumulative = report["top_cumulative_functions"]
    assert cumulative == sorted(
        cumulative,
        key=lambda item: (-item["cumulative_seconds"], item["function"]),
    )
    assert json.loads(json.dumps(report)) == report


def test_profile_runs_activation_and_tool_routing_workloads(tmp_path):
    (tmp_path / "app.py").write_text(
        "def helper():\n    return 1\n\n"
        "def run():\n    return helper()\n",
        encoding="utf-8",
    )
    _write_json(tmp_path / "activation.json", _activation_dataset())
    _write_json(tmp_path / "routing.json", _tool_dataset())
    spec = {
        "schema": PROFILE_SCHEMA,
        "name": "tiny",
        "top_n": 4,
        "workloads": [
            {
                "name": "activation",
                "kind": "activation",
                "dataset": "activation.json",
                "iterations": 1,
                "strategy": "adaptive",
                "context_strategy": "minimal",
            },
            {
                "name": "routing",
                "kind": "tool_routing",
                "dataset": "routing.json",
                "iterations": 2,
            },
        ],
    }

    result = run_profile(spec, tmp_path, spec_directory=tmp_path)

    assert result["schema"] == PROFILE_SCHEMA
    assert result["project_root"] == tmp_path.name
    assert [item["name"] for item in result["workloads"]] == ["activation", "routing"]
    activation, routing = result["workloads"]
    assert activation["workload_summary"]["task_count"] == 1
    assert activation["workload_summary"]["graph_nodes"] >= 2
    assert routing["workload_summary"]["task_count"] == 2
    assert routing["workload_summary"]["top1_accuracy"] == 1.0
    assert all(item["total_calls"] > 0 for item in result["workloads"])


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda spec: spec.update(schema="wrong"), "unsupported"),
        (lambda spec: spec.update(workloads=[]), "non-empty"),
        (lambda spec: spec["workloads"][0].update(name=""), "non-empty name"),
        (lambda spec: spec["workloads"][0].update(kind="wrong"), "kind"),
        (lambda spec: spec["workloads"][0].update(dataset=""), "dataset path"),
        (lambda spec: spec["workloads"][0].update(iterations=0), "positive integer"),
        (lambda spec: spec.update(top_n=0), "top_n"),
    ],
)
def test_profile_spec_validation(mutation, message):
    spec = {
        "schema": PROFILE_SCHEMA,
        "workloads": [
            {"name": "routing", "kind": "tool_routing", "dataset": "routing.json"},
        ],
    }
    mutation(spec)
    with pytest.raises(ValueError, match=message):
        validate_spec(spec)


def test_profile_callable_rejects_invalid_configuration(tmp_path):
    with pytest.raises(ValueError, match="profile name"):
        profile_callable("", lambda: None, source_root=tmp_path)
    with pytest.raises(ValueError, match="top_n"):
        profile_callable("x", lambda: None, source_root=tmp_path, top_n=0)


def test_profile_requires_a_project_directory(tmp_path):
    spec = {
        "schema": PROFILE_SCHEMA,
        "workloads": [
            {"name": "routing", "kind": "tool_routing", "dataset": "missing.json"},
        ],
    }
    with pytest.raises(ValueError, match="project root"):
        run_profile(spec, tmp_path / "missing", spec_directory=tmp_path)
