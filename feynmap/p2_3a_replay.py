"""P2.3a: validate opt-in symbol-evidence packing on a newly sealed corpus.

Gold source labels are checked independently from bytes before search and are
read for scoring ONLY after every arm has packed the identical activated graph.
Original P1/P2.2 manifests and default packer are not rewritten or re-scored.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .context_pipeline import SparseContextPipeline
from .engine import FeynMapEngine
from .p1_replay_acceptance import git_blob_sha
from .p2_delivery_experiment import (
    _measure_arm, _source_definitions, _validate_labels, _validate_source_blobs,
    compact_json, load_frozen_manifest, source_path,
)

MANIFEST_SCHEMA = "feynmap.p2_3a_new_source_manifest.v1"
RESULT_SCHEMA = "feynmap.p2_3a_symbol_evidence_comparison.v1"
NEW_SOURCE_MANIFEST_BLOB = "0512100c4a1c76969e1cfc1c8bc16d6c0fa42e18"
FRESH_IDS = (
    "dispatch-capacity-implementation",
    "dispatch-escalation-implementation",
    "dispatch-capacity-regression-test",
    "dispatch-priority-migration",
    "dispatch-priority-migration-test",
    "dispatch-close-implementation",
    "javascript-alert-implementation",
    "javascript-alert-regression-test",
)


def load_fresh_manifest(path: Path) -> Dict[str, Any]:
    data = path.read_bytes()
    if git_blob_sha(data) != NEW_SOURCE_MANIFEST_BLOB:
        raise ValueError("P2.3a independent source manifest tampered after pre-registration")
    result = json.loads(data)
    if result.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("P2.3a unexpected manifest schema")
    if tuple(item["id"] for item in result.get("tasks", [])) != FRESH_IDS:
        raise ValueError("P2.3a frozen task identities or ordering changed")
    if [row["id"] for row in result["budgets"]] != ["tight", "standard"]:
        raise ValueError("P2.3a budget identities changed")
    if [row["id"] for row in result["arms"]] != [
        "legacy", "p2_1_source_first", "p2_3a_symbol_evidence",
    ]:
        raise ValueError("P2.3a arm identities changed")
    return result


def _javascript_definitions(file: Path) -> set:
    """Separate *textual* source-declaration check; never use graph as gold.

    This is intentionally narrow and fail-closed for these preauthored JS
    fixtures. Parsing remains FeynMap's job; this source check cannot claim
    that a detected function resolves through an import or executes correctly.
    """
    text = file.read_text(encoding="utf-8")
    function = re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    )
    return {(match.group(1),) for match in function.finditer(text)}


def verify_fresh_source(manifest: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    source = manifest["source"]
    declarations = {}
    for path, expected_sha in source["blobs"].items():
        file = root / path
        if not file.is_file():
            raise ValueError("P2.3a source file missing: " + path)
        if git_blob_sha(file.read_bytes()) != expected_sha:
            raise ValueError("P2.3a source file blob mismatch: " + path)
        if file.suffix == ".py":
            declarations[path] = _source_definitions(file)
        elif file.suffix in {".js", ".jsx", ".mjs"}:
            declarations[path] = _javascript_definitions(file)
        else:
            raise ValueError("P2.3a source file type not preauthored: " + path)
    _validate_labels(manifest["tasks"], source, declarations)
    return {"files_verified": len(declarations), "declarations": declarations}


def compare(
    manifest: Mapping[str, Any],
    root: Path,
    *,
    existing_p2: bool = False,
) -> Dict[str, Any]:
    if existing_p2:
        source = manifest["source_fixtures"]["stockroom-independent"]
        verified = _validate_source_blobs(source, root)
        tasks = [
            item for item in manifest["tasks"]
            if item["cohort"] == "stockroom-independent"
        ]
        _validate_labels(tasks, source, verified["declarations"])
        arms = [
            manifest["arms"][0],
            manifest["arms"][1],
            {"id": "p2_3a_symbol_evidence",
             "policy": {"mode": "symbol_evidence",
                        "min_implementation_files": 2,
                        "max_test_fraction": 0.35}},
        ]
        cohort = "p2_2_stockroom_diagnostic_not_fresh"
    else:
        verified = verify_fresh_source(manifest, root)
        source = manifest["source"]
        tasks = manifest["tasks"]
        arms = manifest["arms"]
        cohort = "fresh_dispatch_mixed_language"

    start = time.perf_counter()
    graph = FeynMapEngine().analyze(
        str(root),
        language=source["language"],
        framework=source["framework"],
    )
    analysis_ms = round((time.perf_counter() - start) * 1000.0, 3)
    if graph.diagnostics.get("errors"):
        raise ValueError("P2.3a source graph validation errors")
    pipeline = SparseContextPipeline(graph)
    reports = []
    for task in tasks:
        activated_start = time.perf_counter()
        conf = manifest["activation"]
        outcome = pipeline.search.concept(
            task["query"],
            seed_limit=conf["seed_limit"],
            candidate_limit=conf["candidate_limit"],
            max_depth=conf["max_depth"],
            beam_width=conf["beam_width"],
            max_nodes=conf["max_nodes"],
            direction=conf["direction"],
        )
        search = outcome.search
        activated_ms = round((time.perf_counter() - activated_start) * 1000.0, 3)
        active = {hit.node.id for hit in search.hits}
        report = {
            "id": task["id"],
            "intent_source_authored": task["intent"],
            "query": task["query"],
            "source_basis": task["source_basis"],
            "shared_activation": {
                "nodes": len(active),
                "edges": len(search.edges),
                "node_ids": sorted(active),
                "source_paths": sorted({
                    source_path(hit.node) for hit in search.hits
                    if source_path(hit.node)
                }),
                "activation_elapsed_ms": activated_ms,
                "search_stage": outcome.stage,
            },
            "budgets": [],
        }
        for budget in manifest["budgets"]:
            measured = [
                _measure_arm(graph, search, task, budget, arm, pipeline.packer)
                for arm in arms
            ]
            for row in measured:
                if not set(row["selected_node_ids"]) <= active:
                    raise ValueError(task["id"] + ": selected a node not activated")
                if not row["all_selected_from_shared_activation_with_endpoints"]:
                    raise ValueError(task["id"] + ": unsupported selected relation")
            report["budgets"].append({
                "id": budget["id"], "limits": budget, "arms": measured,
            })
        reports.append(report)

    summaries = []
    losses = []
    for budget in manifest["budgets"]:
        for arm in arms:
            scoped = [
                next(item for item in row["budgets"] if item["id"] == budget["id"])
                for row in reports
            ]
            measurements = [
                next(item for item in entry["arms"] if item["arm"] == arm["id"])
                for entry in scoped
            ]
            sym_rows = [
                symbol for measurement in measurements
                for symbol in measurement["required_symbols"]
            ]
            file_rows = [
                file for measurement in measurements
                for file in measurement["required_files"]
            ]
            summary = {
                "budget": budget["id"],
                "arm": arm["id"],
                "tasks": len(reports),
                "required_symbols": len(sym_rows),
                "activated_required_symbols": sum(x["activated"] for x in sym_rows),
                "delivered_required_symbols": sum(x["delivered"] for x in sym_rows),
                "required_files": len(file_rows),
                "activated_required_files": sum(x["activated"] for x in file_rows),
                "delivered_required_files": sum(x["delivered"] for x in file_rows),
                "required_test_symbols": sum(x["channel"] == "test" for x in sym_rows),
                "delivered_test_symbols": sum(
                    x["delivered"] for x in sym_rows if x["channel"] == "test"
                ),
                "required_migration_symbols": sum(
                    x["channel"] == "migration" for x in sym_rows
                ),
                "delivered_migration_symbols": sum(
                    x["delivered"] for x in sym_rows
                    if x["channel"] == "migration"
                ),
                "estimated_context_tokens_sum": sum(
                    row["estimated_context_tokens"] for row in measurements
                ),
                "mean_estimated_context_tokens": round(sum(
                    row["estimated_context_tokens"] for row in measurements
                ) / len(measurements), 2),
                "packer_one_run_total_ms": round(sum(
                    row["packer_elapsed_ms"] for row in measurements
                ), 3),
                "all_packer_sufficiency_flags": [
                    row["sufficient"] for row in measurements
                ],
                "all_armed_budgets_and_activation_provenance_valid": all(
                    row["all_selected_from_shared_activation_with_endpoints"]
                    and row["estimated_context_tokens"] <= budget["max_tokens"]
                    and row["nodes"] <= budget["max_nodes"]
                    and row["edges"] <= budget["max_edges"]
                    and row["token_characters_by_source_role"][
                        "exact_char_accounting_reconciles"
                    ] for row in measurements
                ),
            }
            summaries.append(summary)
        for row in reports:
            trial = next(x for x in row["budgets"] if x["id"] == budget["id"])
            base = next(x for x in trial["arms"] if x["arm"] == "legacy")
            new = next(x for x in trial["arms"]
                       if x["arm"] == "p2_3a_symbol_evidence")
            before = {
                (item["file"], item["name"], item["qualified_name"]): item
                for item in base["required_symbols"]
            }
            after = {
                (item["file"], item["name"], item["qualified_name"]): item
                for item in new["required_symbols"]
            }
            if set(before) != set(after):
                raise ValueError("P2.3a packer arms scored nonidentical gold symbols")
            for label, item in before.items():
                candidate = after[label]
                if item["activated"] != candidate["activated"]:
                    raise ValueError("P2.3a shared activation differs between arms")
                if item["delivered"] and not candidate["delivered"]:
                    losses.append({
                        "task": row["id"], "budget": budget["id"],
                        "label": label, "reason": candidate["outcome"],
                    })

    return {
        "schema": RESULT_SCHEMA,
        "cohort": cohort,
        "status": (
            "measured_with_label_losses" if losses else
            "measured_without_losses_vs_legacy"
        ),
        "preregistered_manifest_git_blob": (
            NEW_SOURCE_MANIFEST_BLOB if not existing_p2 else
            "13595728204cf2bac4cd4242ec6217654ee59cab"
        ),
        "fresh_source": not existing_p2,
        "source_files_verified": verified["files_verified"],
        "graph_nodes": len(graph.nodes), "graph_edges": len(graph.edges),
        "graph_analysis_elapsed_ms": analysis_ms,
        "task_count": len(reports),
        "tasks": reports, "summaries": summaries,
        "required_symbol_losses_vs_legacy": losses,
        "loss_count": len(losses),
        "original_default_changed": False,
        "no_gold_selection_input": True,
        "caveats": [
            "This is a development/benchmark measurement, not an S7 held-out agent repair result.",
            "The fresh fixture was preauthored and pinned before policy implementation, but is not externally source-reviewed.",
            "The reused P2.2 stockroom diagnostic is known development data; do not claim it as fresh corroboration.",
            "An upstream unindexed/unactivated symbol is not counted as a delivery-only failure.",
            "FeynMap's compact JSON char/4 is a deterministic estimator, not vendor token usage or answer correctness.",
            "The selector does not read source-authored essential_files or symbols; only the scorer does.",
        ],
    }


def as_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# P2.3a symbol-evidence delivery",
        "",
        "**%s** · %s cases · %s source files verified · "
        "%s required-symbol losses vs default legacy across budgets." % (
            result["status"], result["task_count"],
            result["source_files_verified"], result["loss_count"],
        ),
        "",
        "| Budget | Arm | Required symbols activated/delivered | "
        "Files activated/delivered | Required tests | Required migrations | "
        "Mean context char/4 estimate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["summaries"]:
        lines.append("| %s | %s | %s/%s → %s | %s/%s → %s | %s/%s | "
                     "%s/%s | %s |" % (
            row["budget"], row["arm"],
            row["activated_required_symbols"], row["required_symbols"],
            row["delivered_required_symbols"],
            row["activated_required_files"], row["required_files"],
            row["delivered_required_files"],
            row["delivered_test_symbols"], row["required_test_symbols"],
            row["delivered_migration_symbols"], row["required_migration_symbols"],
            row["mean_estimated_context_tokens"],
        ))
    lines.extend(["", "Losses vs legacy (same source activation):", ""])
    if not result["required_symbol_losses_vs_legacy"]:
        lines.append("- None on this source-labelled development fixture.")
    for entry in result["required_symbol_losses_vs_legacy"]:
        lines.append("- %s/%s: %s (%s)" % (
            entry["task"], entry["budget"], entry["label"], entry["reason"]
        ))
    lines.extend([
        "",
        "File-level coverage does not prove symbol-level coverage. "
        "Only source-anchored semantic node IDs/relationships are measured; "
        "this is not literal source-byte recall or downstream answer fidelity.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--previous-p2", action="store_true")
    args = parser.parse_args(argv)
    output = Path(args.output)
    markdown = Path(args.markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.previous_p2:
            manifest = load_frozen_manifest(Path(args.manifest))
        else:
            manifest = load_fresh_manifest(Path(args.manifest))
        report = compare(
            manifest,
            Path(args.project_root).resolve(),
            existing_p2=args.previous_p2,
        )
        status = 0
    except Exception as exc:
        report = {
            "schema": RESULT_SCHEMA,
            "status": "integrity_or_analysis_error",
            "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(),
        }
        status = 1
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    if status:
        markdown.write_text("# P2.3a failed source/measurement integrity\n\n"
                            + report["error"] + "\n", encoding="utf-8")
        print(report["error"], file=sys.stderr)
    else:
        markdown.write_text(as_markdown(report), encoding="utf-8")
        print(as_markdown(report))
    return status


if __name__ == "__main__":
    sys.exit(main())
