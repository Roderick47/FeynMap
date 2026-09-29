"""Collect P2.2 comparisons without converting measurement misses to fake passes.

Integrity errors fail CI; an observed policy regression is reported explicitly
as a research result, rather than edited out of the preauthored oracle.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .p2_delivery_experiment import (
    FROZEN_MANIFEST_GIT_BLOB, SCHEMA, compact_json, load_frozen_manifest,
)

COLLECTION_SCHEMA = "feynmap.p2_2_delivery_collection.v1"


def collect(manifest: Mapping[str, Any],
            reports: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    failures = []
    expected_fixtures = set(manifest["source_fixtures"])
    if set(reports) != expected_fixtures:
        failures.append("fixture report identities differ from frozen source manifest")
    expected_tasks = {row["id"]: row for row in manifest["tasks"]}
    task_rows = {}
    counters = {}
    notes = []
    for fixture_id, source in manifest["source_fixtures"].items():
        report = reports.get(fixture_id) or {}
        if report.get("status") != "measured_with_source_gaps":
            failures.append(fixture_id + ": incomplete/errored analysis")
            continue
        if report.get("frozen_manifest_git_blob") != FROZEN_MANIFEST_GIT_BLOB:
            failures.append(fixture_id + ": manifest identity mismatch")
        if report.get("source_files_blobs_verified") != len(source["blobs"]):
            failures.append(fixture_id + ": frozen source coverage mismatch")
        if source["kind"] == "reused_p1_public_revision_new_symbol_criteria" and (
            report.get("source_revision") != source["revision"]
        ):
            failures.append(fixture_id + ": revision mismatch")
        tasks = report.get("tasks") or []
        scoped = {k: v for k, v in expected_tasks.items() if v["cohort"] == fixture_id}
        if (
            report.get("task_count") != len(scoped)
            or len(tasks) != len(scoped)
            or {task.get("id") for task in tasks} != set(scoped)
        ):
            failures.append(fixture_id + ": task count/identity differs from frozen labels")
        for task in tasks:
            tid = task["id"]
            if tid in task_rows:
                failures.append(tid + ": duplicated report task")
                continue
            task_rows[tid] = task
            spec = scoped.get(tid)
            if not spec:
                failures.append(tid + ": task not present in frozen cohort")
                continue
            if task.get("query") != spec["query"] or task.get("cohort") != fixture_id:
                failures.append(tid + ": query/cohort was changed after freeze")
            budgets = task.get("budget_comparisons") or []
            if [item.get("id") for item in budgets] != [
                item["id"] for item in manifest["budgets"]
            ]:
                failures.append(tid + ": budget identity differs from frozen manifest")
                continue
            for budget, limit in zip(budgets, manifest["budgets"]):
                if budget.get("limits") != limit:
                    failures.append(tid + ": budget caps differ from frozen manifest")
                arms = budget.get("arms") or []
                if [row.get("arm") for row in arms] != [
                    row["id"] for row in manifest["arms"]
                ]:
                    failures.append(tid + ": arm identity/order differs from freeze")
                    continue
                by_id = {row["arm"]: row for row in arms}
                for arm, frozen_arm in zip(arms, manifest["arms"]):
                    key = (fixture_id, budget["id"], arm["arm"])
                    stat = counters.setdefault(key, {
                        "tasks": 0, "file_required": 0, "file_activated": 0,
                        "file_delivered": 0, "symbol_required": 0,
                        "symbol_activated": 0, "symbol_delivered": 0,
                        "test_required": 0, "test_delivered": 0,
                        "migration_required": 0, "migration_delivered": 0,
                        "labeled_distractor_chars": 0,
                        "labeled_distractor_nodes": 0,
                        "delivered_tokens": 0, "delivered_nodes": 0,
                        "pack_ms": 0.0,
                    })
                    stat["tasks"] += 1
                    if arm.get("policy") != frozen_arm["policy"]:
                        failures.append(tid + ": policy parameters changed from freeze")
                    limits = {k: arm.get(k) for k in ("max_tokens", "max_nodes", "max_edges")}
                    if limits != {
                        k: limit[k] for k in ("max_tokens", "max_nodes", "max_edges")
                    }:
                        failures.append(tid + ": policy used nonidentical budget")
                    if (
                        not arm.get("all_selected_from_shared_activation_with_endpoints")
                        or arm.get("nodes") != len(set(arm.get("selected_node_ids") or []))
                        or arm.get("edges") != len(set(arm.get("selected_edge_ids") or []))
                        or arm.get("nodes", -1) > limit["max_nodes"]
                        or arm.get("edges", -1) > limit["max_edges"]
                        or arm.get("estimated_context_tokens", -1) > limit["max_tokens"]
                    ):
                        failures.append(tid + ": invalid selection, provenance or budget")
                    accounting = arm.get("token_characters_by_source_role") or {}
                    if (
                        not accounting.get("exact_char_accounting_reconciles")
                        or accounting.get("estimated_full_tokens") != arm.get(
                            "estimated_context_tokens"
                        )
                        or accounting.get("node_chars", -1)
                           + accounting.get("common_edges_anchors_metadata_separator_chars", -1)
                           != accounting.get("deterministic_full_json_characters")
                        or sum((accounting.get("source_role_node_chars") or {}).values())
                           != accounting.get("node_chars")
                        or sum((arm.get("node_counts_by_channel") or {}).values())
                           != arm.get("nodes")
                    ):
                        failures.append(tid + ": JSON role-character budget does not reconcile")

                    required_file_rows = arm.get("required_files") or []
                    required_symbol_rows = arm.get("required_symbols") or []
                    if [row.get("file") for row in required_file_rows] != sorted(
                        spec["required_files"]
                    ):
                        failures.append(tid + ": required file labels changed")
                    if [
                        (row.get("file"), row.get("name"), row.get("qualified_name"))
                        for row in required_symbol_rows
                    ] != [
                        (row["file"], row["name"], row.get("qualified_name"))
                        for row in spec["required_symbols"]
                    ]:
                        failures.append(tid + ": required granular labels changed")
                    if len(arm.get("optional_useful_support_symbols") or []) != len(
                        spec.get("useful_support_symbols") or []
                    ) or len(arm.get("source_authored_distractor_symbols") or []) != len(
                        spec.get("distractor_symbols") or []
                    ):
                        failures.append(tid + ": optional/distractor label count changed")

                    stat["file_required"] += len(required_file_rows)
                    stat["file_activated"] += sum(bool(row.get("activated")) for row in required_file_rows)
                    stat["file_delivered"] += sum(bool(row.get("delivered")) for row in required_file_rows)
                    stat["symbol_required"] += len(required_symbol_rows)
                    stat["symbol_activated"] += sum(bool(row.get("activated")) for row in required_symbol_rows)
                    stat["symbol_delivered"] += sum(bool(row.get("delivered")) for row in required_symbol_rows)
                    for row in required_symbol_rows:
                        if row["channel"] == "test":
                            stat["test_required"] += 1
                            stat["test_delivered"] += bool(row["delivered"])
                        if row["channel"] == "migration":
                            stat["migration_required"] += 1
                            stat["migration_delivered"] += bool(row["delivered"])
                    stat["labeled_distractor_chars"] += accounting.get(
                        "preauthored_distractor_node_chars", 0
                    )
                    stat["labeled_distractor_nodes"] += accounting.get(
                        "preauthored_distractor_node_count", 0
                    )
                    stat["delivered_tokens"] += arm.get("estimated_context_tokens", 0)
                    stat["delivered_nodes"] += arm.get("nodes", 0)
                    stat["pack_ms"] += arm.get("packer_elapsed_ms", 0.0)

                baseline = by_id["legacy"]
                v1 = by_id["source_first_p21"]
                balanced = by_id["balanced_floor1"]
                for rival in (v1, balanced):
                    role = rival["arm"]
                    for label_kind, label_property in (
                        ("required_symbols", ("file", "name", "qualified_name")),
                        ("required_files", ("file",)),
                    ):
                        baseline_by_label = {
                            tuple(row.get(k) for k in label_property): row
                            for row in baseline[label_kind]
                        }
                        rival_by_label = {
                            tuple(row.get(k) for k in label_property): row
                            for row in rival[label_kind]
                        }
                        if set(baseline_by_label) != set(rival_by_label):
                            failures.append(tid + ": arms scored different frozen labels")
                            continue
                        for label, before in baseline_by_label.items():
                            after = rival_by_label[label]
                            if before["activated"] != after["activated"]:
                                failures.append(tid + ": different activation supplied to policies")
                            if before["delivered"] and not after["delivered"]:
                                notes.append({
                                    "fixture": fixture_id, "task": tid,
                                    "budget": budget["id"], "policy": role,
                                    "regression": label_kind,
                                    "lost_previously_delivered_label": label,
                                    "source_channel": after["channel"],
                                    "reason": after["outcome"],
                                })

    if set(task_rows) != set(expected_tasks):
        failures.append("not every original preauthored task was reported")
    summaries = []
    for (fixture, budget, arm), metric in sorted(counters.items()):
        summary = {
            "fixture": fixture, "budget": budget, "arm": arm,
            **metric,
            "file_recall": (
                round(metric["file_delivered"] / metric["file_required"], 4)
                if metric["file_required"] else None
            ),
            "symbol_recall": (
                round(metric["symbol_delivered"] / metric["symbol_required"], 4)
                if metric["symbol_required"] else None
            ),
            "conditional_symbol_delivery_recall": (
                round(metric["symbol_delivered"] / metric["symbol_activated"], 4)
                if metric["symbol_activated"] else None
            ),
            "required_test_evidence_recall": (
                round(metric["test_delivered"] / metric["test_required"], 4)
                if metric["test_required"] else None
            ),
            "required_migration_evidence_recall": (
                round(metric["migration_delivered"] / metric["migration_required"], 4)
                if metric["migration_required"] else None
            ),
            "labeled_distractor_token_equivalent_approx": round(
                metric["labeled_distractor_chars"] / 4, 2
            ),
            "mean_estimated_context_tokens": round(
                metric["delivered_tokens"] / metric["tasks"], 2
            ) if metric["tasks"] else None,
            "mean_pack_ms_one_run": round(
                metric["pack_ms"] / metric["tasks"], 3
            ) if metric["tasks"] else None,
        }
        summaries.append(summary)
    return {
        "schema": COLLECTION_SCHEMA,
        "status": "integrity_failure" if failures else (
            "measured_with_policy_regressions" if notes else
            "measured_no_label_regressions_against_legacy"
        ),
        "frozen_manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "fixtures": len(reports), "tasks": len(task_rows),
        "budget_count": len(manifest["budgets"]),
        "arm_count": len(manifest["arms"]),
        "summaries": summaries,
        "policy_label_regressions_vs_legacy": notes,
        "policy_label_regression_count": len(notes),
        "integrity_errors": failures,
        "limitations": [
            "Do not treat missing preauthored symbols as non-errors. Activation and delivery misses are separately exposed in raw reports.",
            "Reused DRF calibration source is not independent or S7 held-out; the new stockroom fixture is independently authored but not third-party reviewed.",
            "Label regression means one originally delivered source-authored item is now omitted; some optional support may still be useful even when not designated essential.",
            "Exact channel breakdown uses compact-JSON characters; char/4 is FeynMap's deterministic heuristic, not an LLM tokenizer.",
            "Only preauthored named symbols are called distractors. Remaining unlabelled nodes are unclassified, not presumed irrelevant.",
            "These are one-run context delivery comparisons, not answer correctness or agent-task improvement claims.",
        ],
    }


def as_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# P2.2 independent source-role delivery comparison",
        "",
        "**%s** | %s tasks | %s budgets | %s policy arms | "
        "%s previously delivered labels lost by an experimental policy." % (
            result["status"], result["tasks"], result["budget_count"],
            result["arm_count"], result["policy_label_regression_count"],
        ),
        "",
        "| Cohort | Budget | Arm | File recall | Symbol recall | "
        "Test recall | Migration recall | Approx labeled distractor equivalents | "
        "Mean context estimator |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["summaries"]:
        def val(key):
            return "n/a" if row.get(key) is None else str(row[key])
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row["fixture"], row["budget"], row["arm"],
            val("file_recall"), val("symbol_recall"),
            val("required_test_evidence_recall"),
            val("required_migration_evidence_recall"),
            val("labeled_distractor_token_equivalent_approx"),
            val("mean_estimated_context_tokens"),
        ))
    lines.extend([
        "",
        "Critical: file presence is not granular symbol recall; the latter is "
        "listed separately. Missing activation cannot be repaired by a packer. "
        "Only preauthored source labels count as distractors, and exact "
        "model-token cost and downstream answer correctness are **unmeasured**.",
        "",
    ])
    if result["policy_label_regressions_vs_legacy"]:
        lines.append("## Observed policy label regressions (not hidden)")
        lines.append("")
        for row in result["policy_label_regressions_vs_legacy"]:
            lines.append("- %s/%s/%s/%s: %s %s, channel %s (%s)" % (
                row["fixture"], row["task"], row["budget"], row["policy"],
                row["regression"], row["lost_previously_delivered_label"],
                row["source_channel"], row["reason"],
            ))
    if result["integrity_errors"]:
        lines.extend(["", "## Integrity failures", ""])
        lines += ["- " + error for error in result["integrity_errors"]]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--reports-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--markdown", required=True)
    args = p.parse_args(argv)
    output, md = Path(args.output), Path(args.markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    md.parent.mkdir(parents=True, exist_ok=True)
    try:
        manifest = load_frozen_manifest(Path(args.manifest))
        reports = {}
        for file in Path(args.reports_dir).glob("p2-2-*.json"):
            value = json.loads(file.read_text(encoding="utf-8"))
            identifier = value.get("fixture_id")
            if not identifier or identifier in reports:
                raise ValueError("missing or duplicated fixture report identifier: " + str(file))
            if value.get("schema") != SCHEMA:
                raise ValueError("invalid experiment report schema in " + str(file))
            reports[identifier] = value
        result = collect(manifest, reports)
        exit_code = int(bool(result["integrity_errors"]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {
            "schema": COLLECTION_SCHEMA, "status": "integrity_failure",
            "tasks": 0, "budget_count": 0, "arm_count": 0,
            "policy_label_regression_count": 0,
            "summaries": [], "policy_label_regressions_vs_legacy": [],
            "integrity_errors": [type(exc).__name__ + ": " + str(exc)],
        }
        exit_code = 1
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    md.write_text(as_markdown(result), encoding="utf-8")
    print(as_markdown(result))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
