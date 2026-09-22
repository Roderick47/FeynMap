import copy
import json
from pathlib import Path

import pytest

from feynmap.judgment.ai_repair_benchmark import ARMS, content_hash
from feynmap.judgment.swebench_r1 import (
    GENERATION_SCHEMA,
    REPORT_SCHEMA,
    SELECTION_SCHEMA,
    _arm_order,
    _patch_paths,
    aggregate_results,
    capture_swebench_patch,
    build_selection,
    export_predictions,
    validate_selection,
)


def _rows(count=10):
    result = []
    for index in range(count):
        result.append(
            {
                "instance_id": "owner__repo-%d" % index,
                "repo": "owner/repo-%d" % (index % 5),
                "base_commit": "%040x" % (index + 1),
                "problem_statement": "Repair historical issue %d." % index,
                "version": "1.%d" % index,
                "patch": (
                    "diff --git a/pkg/file%d.py b/pkg/file%d.py\n"
                    "--- a/pkg/file%d.py\n"
                    "+++ b/pkg/file%d.py\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                )
                % (index, index, index, index),
                "test_patch": "SECRET TEST PATCH %d" % index,
                "FAIL_TO_PASS": json.dumps(["test_%d" % index]),
                "PASS_TO_PASS": json.dumps(["existing_%d" % index]),
                "hints_text": "SECRET HINT %d" % index,
            }
        )
    return result


def test_selection_is_deterministic_and_contains_no_gold_fields():
    rows = _rows()
    first = build_selection(
        rows,
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        corpus_id="r1-test",
        count=8,
        max_per_repo=2,
        selected_at="2026-09-22T00:00:00+00:00",
    )
    second = build_selection(
        copy.deepcopy(rows),
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        corpus_id="r1-test",
        count=8,
        max_per_repo=2,
        selected_at="2026-09-22T00:00:00+00:00",
    )

    assert first == second
    assert first["schema"] == SELECTION_SCHEMA
    assert len(first["tasks"]) == 8
    rendered = json.dumps(first, sort_keys=True)
    assert "SECRET TEST PATCH" not in rendered
    assert "SECRET HINT" not in rendered

    selected_task_keys = {key for task in first["tasks"] for key in task}
    assert "patch" not in selected_task_keys
    assert "test_patch" not in selected_task_keys
    assert "FAIL_TO_PASS" not in selected_task_keys
    assert "PASS_TO_PASS" not in selected_task_keys
    assert "hints_text" not in selected_task_keys
    assert set(first["selection_policy"]["excluded_gold_keys"]) >= {
        "patch",
        "test_patch",
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "hints_text",
    }

    counts = {}
    for task in first["tasks"]:
        counts[task["repo"]] = counts.get(task["repo"], 0) + 1
    assert max(counts.values()) <= 2
    validate_selection(first, rows)


def test_selection_is_independent_of_gold_patch_and_test_contents():
    rows = _rows()
    original = build_selection(
        rows,
        dataset_name="verified",
        split="test",
        corpus_id="r1-gold-blind",
        count=5,
        selected_at="2026-09-22T00:00:00+00:00",
    )
    changed = copy.deepcopy(rows)
    for index, row in enumerate(changed):
        row["patch"] = "COMPLETELY DIFFERENT GOLD %d" % index
        row["test_patch"] = "COMPLETELY DIFFERENT TEST %d" % index
        row["FAIL_TO_PASS"] = json.dumps(["secret_changed_%d" % index])
        row["PASS_TO_PASS"] = json.dumps([])
        row["hints_text"] = "different hidden hint"

    repeated = build_selection(
        changed,
        dataset_name="verified",
        split="test",
        corpus_id="r1-gold-blind",
        count=5,
        selected_at="2026-09-22T00:00:00+00:00",
    )
    assert repeated == original


def test_arm_order_is_a_deterministic_counterbalanced_rotation():
    orders = [_arm_order("task-%d" % index) for index in range(20)]
    assert all(set(order) == set(ARMS) and len(order) == len(ARMS) for order in orders)
    assert all(order == _arm_order("task-%d" % index) for index, order in enumerate(orders))
    assert len({tuple(order) for order in orders}) > 1


def test_selection_validation_detects_metadata_tampering():
    rows = _rows()
    selection = build_selection(
        rows,
        dataset_name="verified",
        split="test",
        corpus_id="r1-test",
        count=5,
        selected_at="2026-09-22T00:00:00+00:00",
    )
    changed = copy.deepcopy(rows)
    selected_id = selection["tasks"][0]["instance_id"]
    for row in changed:
        if row["instance_id"] == selected_id:
            row["problem_statement"] += " tampered"
            break

    with pytest.raises(ValueError, match="no longer matches"):
        validate_selection(selection, changed)


def test_patch_paths_extracts_reference_changed_files_only_once():
    patch = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-a
+b
diff --git a/pkg/b.py b/pkg/b.py
--- a/pkg/b.py
+++ b/pkg/b.py
@@ -1 +1 @@
-a
+b
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -4 +4 @@
-x
+y
"""
    assert _patch_paths(patch) == ["a.py", "pkg/b.py"]


def _spec():
    tasks = []
    for index in range(2):
        tasks.append(
            {
                "id": "instance-%d" % index,
                "description": "Repair issue %d." % index,
                "repository": {
                    "locator": "path:/tmp/instance-%d" % index,
                    "revision": "%040x" % (index + 1),
                    "content_hash_policy": "canonical_text_lf_v1",
                    "content_hash": "%064x" % (index + 10),
                },
                "oracle": {
                    "required_tests": [
                        {
                            "id": "swebench-resolved",
                            "command": ["external:swebench"],
                        }
                    ],
                    "acceptable_change_sets": [
                        {
                            "required_files": ["pkg/target%d.py" % index],
                            "allowed_files": ["pkg/target%d.py" % index],
                        }
                    ],
                    "forbidden_files": [],
                    "sealed_files": [],
                    "baseline_expectation": "at_least_one_failure",
                },
                "external_evaluator": {
                    "kind": "swebench",
                    "dataset_name": "verified",
                    "split": "test",
                    "instance_id": "instance-%d" % index,
                    "repo": "owner/repo",
                    "base_commit": "%040x" % (index + 1),
                    "gold_changed_files_proxy": ["pkg/target%d.py" % index],
                },
            }
        )
    return {
        "schema": "feynmap.ai_repair_benchmark.v1",
        "name": "test",
        "evaluation_tier": "held_out",
        "arms": list(ARMS),
        "tasks": tasks,
    }


def _record(spec, task_index, arm, resolved=True):
    task_id = "instance-%d" % task_index
    model = "model/%s" % arm
    record = {
        "schema": GENERATION_SCHEMA,
        "benchmark_hash": content_hash(spec),
        "task_id": task_id,
        "instance_id": task_id,
        "arm": arm,
        "context_hash": None if arm == "unassisted" else ("%064x" % 77),
        "repository": dict(spec["tasks"][task_index]["repository"]),
        "agent": {"provider": "test", "model": "model"},
        "prediction": {
            "instance_id": task_id,
            "model_name_or_path": model,
            "model_patch": "diff",
        },
        "outcome": {
            "patch_produced": True,
            "patch_sha256": "%064x" % 99,
            "changed_files": ["pkg/target%d.py" % task_index],
            "first_proposed_edit": {"path": "pkg/target%d.py" % task_index},
            "unsupported_claims": [],
            "repository_searches": task_index + 1,
            "extra_context_requests": 0,
            "elapsed_seconds": 3.0 + task_index,
            "usage": {"input_tokens": 100 + task_index, "output_tokens": 20},
        },
    }
    record["generation_id"] = content_hash(record)
    return record


def test_swebench_patch_handles_modified_created_and_deleted_files(tmp_path: Path):
    baseline = tmp_path / "baseline"
    workspace = tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()

    (baseline / "keep.py").write_text("old\n", encoding="utf-8")
    (workspace / "keep.py").write_text("new\n", encoding="utf-8")
    (workspace / "created.py").write_text("created\n", encoding="utf-8")
    (baseline / "deleted.py").write_text("deleted\n", encoding="utf-8")

    changed, patch, digest = capture_swebench_patch(baseline, workspace)

    assert changed == ["created.py", "deleted.py", "keep.py"]
    assert "diff --git a/created.py b/created.py" in patch
    assert "--- /dev/null" in patch
    assert "+++ b/created.py" in patch
    assert "diff --git a/deleted.py b/deleted.py" in patch
    assert "--- a/deleted.py" in patch
    assert "+++ /dev/null" in patch
    assert "diff --git a/keep.py b/keep.py" in patch
    assert len(digest) == 64


def test_export_predictions_uses_official_swebench_shape():
    spec = _spec()
    records = [_record(spec, index, "unassisted") for index in range(2)]
    payload = export_predictions(records, arm="unassisted")
    rows = [json.loads(line) for line in payload.splitlines()]

    assert [row["instance_id"] for row in rows] == ["instance-0", "instance-1"]
    assert all(set(row) == {"instance_id", "model_name_or_path", "model_patch"} for row in rows)


def test_aggregate_uses_official_resolved_as_primary_metric(tmp_path: Path):
    spec = _spec()
    records = []
    for task_index in range(2):
        for arm in ARMS:
            record = _record(spec, task_index, arm)
            records.append(record)
            model_dir = (
                tmp_path
                / record["prediction"]["model_name_or_path"].replace("/", "__")
                / record["instance_id"]
            )
            model_dir.mkdir(parents=True)
            # Assisted arms resolve both tasks; unassisted resolves one.
            resolved = arm != "unassisted" or task_index == 0
            report = {
                record["instance_id"]: {
                    "patch_is_None": False,
                    "patch_exists": True,
                    "patch_successfully_applied": True,
                    "resolved": resolved,
                    "infra_failure": False,
                }
            }
            (model_dir / "report.json").write_text(
                json.dumps(report), encoding="utf-8"
            )

    result = aggregate_results(spec, records, run_root=tmp_path)

    assert result["schema"] == REPORT_SCHEMA
    assert result["primary_metric"] == "official_swebench_resolved_rate"
    assert result["by_arm"]["unassisted"]["resolved_rate"] == 0.5
    assert result["by_arm"]["deterministic_context"]["resolved_rate"] == 1.0
    assert result["deltas_from_unassisted"]["deterministic_context"]["resolved_rate"] == 0.5
    assert result["by_arm"]["dual_channel"]["first_edit_gold_file_proxy_rate"] == 1.0
