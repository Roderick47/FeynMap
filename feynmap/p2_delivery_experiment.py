"""P2.2: preauthored source-label channel budget experiment.

Both packers consume ONE identical S2 activation per task. Frozen labels are
used only AFTER their outputs have been selected. This is a development-set
context-delivery measurement, not model-answer/agent-repair validation.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import subprocess
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .context import estimate_tokens
from .context_pipeline import SparseContextPipeline
from .delivery_channels import DeliveryChannelPolicy, channel_counts, file_channel, task_channel
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .p1_replay_acceptance import git_blob_sha

SCHEMA = "feynmap.p2_2_delivery_report.v1"
MANIFEST_SCHEMA = "feynmap.p2_delivery_experiment_manifest.v1"
# Locked BEFORE any P2.2 source analysis. Changes require an explicit new
# experiment, not rewriting observations to satisfy an oracle.
FROZEN_MANIFEST_GIT_BLOB = "13595728204cf2bac4cd4242ec6217654ee59cab"


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def source_path(node: Any) -> str:
    location = getattr(node, "location", None)
    return str(getattr(location, "path", "") or "").replace("\\", "/").lstrip("./")


def _source_definitions(path: Path) -> set:
    """Independent AST declaration check, not a FeynMap node lookup."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()

    def visit(items: Sequence[Any], stack: Tuple[str, ...]) -> None:
        for item in items:
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                path_parts = stack + (item.name,)
                names.add(path_parts)
                visit(item.body, path_parts)
            else:
                # Nested declarative source can occur inside conditions or
                # compound statements without being a module-level function.
                for _, value in ast.iter_fields(item):
                    if isinstance(value, list):
                        visit(value, stack)
    visit(tree.body, ())
    return names


def _validate_source_blobs(source: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    if source["kind"] == "reused_p1_public_revision_new_symbol_criteria":
        git = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True,
        ).stdout.strip()
        if git != source["revision"]:
            raise ValueError("P2.2 pinned external repository revision mismatch: " + git)
    else:
        git = None
    declarations = {}
    for path, expected in source["blobs"].items():
        file = root / path
        if not file.is_file():
            raise ValueError("P2.2 frozen source file absent: " + path)
        actual = git_blob_sha(file.read_bytes())
        if actual != expected:
            raise ValueError("P2.2 frozen source blob mismatch: " + path)
        declarations[path] = _source_definitions(file)
    return {"source_revision": git, "files_verified": len(declarations),
            "declarations": declarations}


def _validate_labels(
    tasks: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    declarations: Mapping[str, set],
) -> None:
    blobs = set(source["blobs"])
    for task in tasks:
        if len(set(task["required_files"])) != len(task["required_files"]):
            raise ValueError(task["id"] + ": duplicate source-required file")
        for path in task["required_files"]:
            if path not in blobs:
                raise ValueError(task["id"] + ": source-required file not frozen: " + path)
        for group in ("required_symbols", "useful_support_symbols", "distractor_symbols"):
            for label in task.get(group) or []:
                path, name = label["file"], label["name"]
                if path not in blobs:
                    raise ValueError(task["id"] + ": labelled symbol source not frozen: " + path)
                qname = label.get("qualified_name")
                if qname:
                    # Source package prefix may contain syntactically invalid
                    # module names (numeric migrations); AST knows the actual
                    # nested Class.method declaration rather than importability.
                    parts = tuple(qname.split("."))
                    matches = [
                        nested for nested in declarations[path]
                        if nested[-1] == name and len(nested) <= len(parts)
                        and nested == parts[-len(nested):]
                    ]
                else:
                    matches = [nested for nested in declarations[path]
                               if nested[-1] == name]
                if not matches:
                    raise ValueError(
                        "%s: preauthored %s symbol absent in frozen source: %s:%s"
                        % (task["id"], group, path, name)
                    )
        if not task.get("required_symbols"):
            raise ValueError(task["id"] + ": no source-authored essential symbols")
        all_labels = [
            compact_json(label) for group in
            ("required_symbols", "useful_support_symbols", "distractor_symbols")
            for label in task.get(group) or []
        ]
        if len(all_labels) != len(set(all_labels)):
            raise ValueError(task["id"] + ": overlapping/duplicate symbol labels")


def load_frozen_manifest(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    if git_blob_sha(raw) != FROZEN_MANIFEST_GIT_BLOB:
        raise ValueError("P2.2 source-authored manifest changed after oracle freeze")
    value = json.loads(raw)
    if value.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("P2.2 incompatible manifest schema")
    if len(value.get("tasks") or []) != 8:
        raise ValueError("P2.2 frozen task count must remain eight")
    ids = [task["id"] for task in value["tasks"]]
    if len(set(ids)) != len(ids):
        raise ValueError("P2.2 duplicate task identity")
    if [row["id"] for row in value["arms"]] != [
        "legacy", "source_first_p21", "balanced_floor1",
    ]:
        raise ValueError("P2.2 the three policy arms are not frozen")
    if [row["id"] for row in value["budgets"]] != ["tight", "standard"]:
        raise ValueError("P2.2 the two budget definitions are not frozen")
    return value


def _graph_label(graph: Any, label: Mapping[str, str]) -> Dict[str, Any]:
    matches = [
        node for node in graph.nodes
        if source_path(node) == label["file"]
        and node.name == label["name"]
        and (
            not label.get("qualified_name")
            or node.qualified_name == label["qualified_name"]
        )
    ]
    return {
        "file": label["file"], "name": label["name"],
        "qualified_name": label.get("qualified_name"),
        "graph_match_count": len(matches),
        "node_ids": sorted(node.id for node in matches),
        "channel": file_channel(label["file"]),
        "graph_index_status": (
            "unique" if len(matches) == 1 else
            "not_indexed" if not matches else "ambiguous"
        ),
    }


def _graph_identity(graph: Any) -> str:
    """Graph ID+evidence digest: packers must not rewrite source truth."""
    material = {
        "nodes": sorted(
            [node.to_dict() for node in graph.nodes],
            key=lambda node: node["id"],
        ),
        "edges": sorted(
            [edge.to_dict() for edge in graph.edges],
            key=lambda edge: edge["id"],
        ),
    }
    return hashlib.sha256(compact_json(material).encode("utf-8")).hexdigest()


def _label_results(
    graph: Any,
    source_labels: Sequence[Mapping[str, Any]],
    activated: set,
    delivered: set,
) -> List[Dict[str, Any]]:
    rows = []
    for label in source_labels:
        resolution = _graph_label(graph, label)
        ids = resolution["node_ids"]
        if resolution["graph_index_status"] != "unique":
            outcome = resolution["graph_index_status"]
        elif ids[0] not in activated:
            outcome = "not_activated"
        elif ids[0] not in delivered:
            outcome = "activated_but_not_delivered"
        else:
            outcome = "delivered"
        resolution.update({
            "outcome": outcome,
            "activated": len(ids) == 1 and ids[0] in activated,
            "delivered": len(ids) == 1 and ids[0] in delivered,
        })
        rows.append(resolution)
    return rows


def _recall(matched: int, total: int) -> Optional[float]:
    return round(float(matched) / total, 6) if total else None


def _role_payload_breakdown(
    graph: Any,
    payload: Mapping[str, Any],
    distractor_ids: set,
    useful_ids: set,
    required_ids: set,
) -> Dict[str, Any]:
    """Exact deterministic JSON character accounting, NOT vendor tokens.

    FeynMap's budget estimate is ceil(full JSON characters / 4). The model
    payload's encoded node chars are attributed to the source role, with all
    edges, anchors, commas and common metadata in separately reconciled
    non-node overhead. Source-author labels identify only named distractors;
    no unlabeled node is automatically declared irrelevant.
    """
    total = len(compact_json(payload))
    by_channel: Dict[str, int] = defaultdict(int)
    labeled = Counter()
    for node in payload["nodes"]:
        identifier = node["id"]
        original = graph.node(identifier)
        role = file_channel(source_path(original) if original else None)
        chars = len(compact_json(node))
        by_channel[role] += chars
        if identifier in distractor_ids:
            labeled["preauthored_distractor_chars"] += chars
            labeled["preauthored_distractor_nodes"] += 1
        if identifier in useful_ids:
            labeled["optional_relevant_chars"] += chars
            labeled["optional_relevant_nodes"] += 1
        if identifier in required_ids:
            labeled["required_symbol_chars"] += chars
            labeled["required_symbol_nodes"] += 1
    node_chars = sum(by_channel.values())
    other = total - node_chars
    if other < 0:
        raise ValueError("P2.2 impossible per-channel JSON character accounting")
    return {
        "deterministic_full_json_characters": total,
        "estimated_full_tokens": int(math.ceil(total / 4.0)),
        "source_role_node_chars": dict(sorted(by_channel.items())),
        "source_role_node_token_equivalents_approx": {
            role: round(chars / 4.0, 2)
            for role, chars in sorted(by_channel.items())
        },
        "common_edges_anchors_metadata_separator_chars": other,
        "node_chars": node_chars,
        "exact_char_accounting_reconciles": node_chars + other == total,
        "preauthored_distractor_node_chars": labeled["preauthored_distractor_chars"],
        "preauthored_distractor_token_equivalent_approx": round(
            labeled["preauthored_distractor_chars"] / 4.0, 2
        ),
        "preauthored_distractor_node_count": labeled["preauthored_distractor_nodes"],
        "required_symbol_node_chars": labeled["required_symbol_chars"],
        "optional_relevant_node_chars": labeled["optional_relevant_chars"],
        "interpretation": (
            "Exact compact-JSON chars under the same char/4 estimate as "
            "FeynMap's budget guard. Role values exclude shared metadata and "
            "edges; not exact vendor tokenizer counts or a blanket claim "
            "that non-required nodes are distractors."
        ),
    }


def _measure_arm(
    graph: Any,
    activation: Any,
    task: Mapping[str, Any],
    budget_spec: Mapping[str, Any],
    arm: Mapping[str, Any],
    packer: Any,
) -> Dict[str, Any]:
    budget = MinimalContextBudget(
        max_tokens=budget_spec["max_tokens"],
        max_nodes=budget_spec["max_nodes"],
        max_edges=budget_spec["max_edges"],
    )
    selection = arm["policy"]
    policy = DeliveryChannelPolicy(**selection) if selection is not None else None
    started = time.perf_counter()
    context = packer.pack(
        activation, budget=budget, delivery_policy=policy,
    )
    pack_ms = (time.perf_counter() - started) * 1000.0
    active_ids = {hit.node.id for hit in activation.hits}
    edges = {
        edge.id: edge for edge in activation.edges
        if edge.source in active_ids and edge.target in active_ids
    }
    selected_ids = set(context.selected_node_ids)
    selected_edge_ids = set(context.selected_edge_ids)
    selected_edges_valid = (
        selected_ids <= active_ids
        and selected_edge_ids <= set(edges)
        and all(
            {edges[identifier].source, edges[identifier].target} <= selected_ids
            for identifier in selected_edge_ids
        )
    )
    if not selected_edges_valid:
        raise ValueError(task["id"] + ": delivery fabricated activation or omitted edge endpoint")
    payload_ids = [node["id"] for node in context.payload["nodes"]]
    if set(payload_ids) != selected_ids or len(payload_ids) != len(selected_ids):
        raise ValueError(task["id"] + ": selected IDs differ from delivered payload")
    if len(context.payload["relationships"]) != len(selected_edge_ids):
        raise ValueError(task["id"] + ": delivered relationship payload is incomplete")
    if context.delivered_tokens != estimate_tokens(context.payload):
        raise ValueError(task["id"] + ": context token estimate is not from delivered payload")
    if (
        context.delivered_tokens > budget.max_tokens
        or context.delivered_nodes > budget.max_nodes
        or len(selected_edge_ids) > budget.max_edges
    ):
        raise ValueError(task["id"] + ": delivery exceeded frozen budget")

    labels = {}
    for key in ("required_symbols", "useful_support_symbols", "distractor_symbols"):
        labels[key] = _label_results(
            graph, task.get(key) or [], active_ids, selected_ids,
        )
    required_file_paths = set(task["required_files"])
    active_paths = {
        source_path(hit.node) for hit in activation.hits if source_path(hit.node)
    }
    delivered_paths = {
        source_path(graph.node(identifier))
        for identifier in selected_ids if graph.node(identifier) is not None
        and source_path(graph.node(identifier))
    }
    required_files = [
        {"file": path, "channel": file_channel(path),
         "activated": path in active_paths, "delivered": path in delivered_paths,
         "outcome": (
             "delivered" if path in delivered_paths
             else "activated_but_not_delivered" if path in active_paths
             else "not_activated"
         )}
        for path in sorted(required_file_paths)
    ]
    req_symbols = labels["required_symbols"]
    req_activated = sum(row["activated"] for row in req_symbols)
    req_delivered = sum(row["delivered"] for row in req_symbols)
    required_test = [row for row in req_symbols if row["channel"] == "test"]
    required_migration = [row for row in req_symbols if row["channel"] == "migration"]
    def ids(group: str) -> set:
        return {
            item for row in labels[group] if row["graph_match_count"] == 1
            for item in row["node_ids"]
        }
    breakdown = _role_payload_breakdown(
        graph, context.payload,
        distractor_ids=ids("distractor_symbols"),
        useful_ids=ids("useful_support_symbols"),
        required_ids=ids("required_symbols"),
    )
    if breakdown["estimated_full_tokens"] != context.delivered_tokens:
        raise ValueError(task["id"] + ": per-channel character estimate disagrees with packer")

    delivered_nodes = [graph.node(identifier) for identifier in context.selected_node_ids]
    counts = channel_counts(delivered_nodes)
    if sum(counts.values()) != context.delivered_nodes:
        raise ValueError(task["id"] + ": channel node counts do not reconcile")
    return {
        "arm": arm["id"],
        "budget": budget_spec["id"],
        "policy": selection,
        "packer_elapsed_ms": round(pack_ms, 3),
        "selected_node_ids": list(context.selected_node_ids),
        "selected_edge_ids": list(context.selected_edge_ids),
        "delivered_files": sorted(delivered_paths),
        "node_counts_by_channel": counts,
        "nodes": context.delivered_nodes,
        "edges": len(selected_edge_ids),
        "estimated_context_tokens": context.delivered_tokens,
        "max_tokens": budget.max_tokens,
        "max_nodes": budget.max_nodes,
        "max_edges": budget.max_edges,
        "sufficient": context.sufficient,
        "critical_node_count": len(context.critical_node_ids),
        "packing_iterations": context.packing_iterations,
        "all_selected_from_shared_activation_with_endpoints": selected_edges_valid,
        "required_files": required_files,
        "required_file_recall": _recall(
            sum(row["delivered"] for row in required_files), len(required_files)
        ),
        "required_file_activation_recall": _recall(
            sum(row["activated"] for row in required_files), len(required_files)
        ),
        "required_symbols": req_symbols,
        "required_symbol_recall": _recall(req_delivered, len(req_symbols)),
        "required_symbol_activation_recall": _recall(req_activated, len(req_symbols)),
        "conditional_delivery_recall_among_activated_required_symbols": (
            _recall(req_delivered, req_activated)
        ),
        "required_test_symbol_recall": _recall(
            sum(row["delivered"] for row in required_test), len(required_test)
        ),
        "required_migration_symbol_recall": _recall(
            sum(row["delivered"] for row in required_migration),
            len(required_migration),
        ),
        "optional_useful_support_symbols": labels["useful_support_symbols"],
        "source_authored_distractor_symbols": labels["distractor_symbols"],
        "token_characters_by_source_role": breakdown,
        "limitations": (
            "Source-authored granular symbols and named distractors only. "
            "Not source-code excerpt recall, true distractor prevalence, "
            "model answer quality or actual tokenizer usage."
        ),
    }


def evaluate_fixture(
    manifest: Mapping[str, Any],
    fixture_id: str,
    root: Path,
) -> Dict[str, Any]:
    source = manifest["source_fixtures"][fixture_id]
    verified = _validate_source_blobs(source, root)
    tasks = [task for task in manifest["tasks"] if task["cohort"] == fixture_id]
    if not tasks:
        raise ValueError("P2.2 unknown/no-task fixture: " + fixture_id)
    _validate_labels(tasks, source, verified["declarations"])

    started = time.perf_counter()
    graph = FeynMapEngine().analyze(
        str(root), language=source["language"], framework=source["framework"]
    )
    analysis_ms = (time.perf_counter() - started) * 1000.0
    if graph.diagnostics.get("errors"):
        raise ValueError("P2.2 graph validation errors: " + str(graph.diagnostics["errors"][:5]))
    initial_graph_identity = _graph_identity(graph)
    pipeline = SparseContextPipeline(graph)
    task_reports = []
    for task in tasks:
        # Only the query and predeclared activation configuration go to search;
        # source-gold file/symbol labels are not examined until PACKING ENDS.
        conf = manifest["activation"]
        activation_start = time.perf_counter()
        activated_result = pipeline.search.concept(
            task["query"],
            seed_limit=conf["seed_limit"],
            candidate_limit=conf["candidate_limit"],
            max_depth=conf["max_depth"],
            beam_width=conf["beam_width"],
            max_nodes=conf["max_nodes"],
            direction=conf["direction"],
        )
        activation_ms = (time.perf_counter() - activation_start) * 1000.0
        activation = activated_result.search
        # The exact same immutable search result object is given to every arm
        # and budget; never rerun search to give one policy better input.
        per_budget = []
        for budget in manifest["budgets"]:
            arms = [
                _measure_arm(graph, activation, task, budget, arm, pipeline.packer)
                for arm in manifest["arms"]
            ]
            if len({
                compact_json([
                    hit.node.id for hit in activation.hits
                ]) for _ in arms
            }) != 1:
                raise ValueError(task["id"] + ": packer arms did not share activation")
            per_budget.append({
                "id": budget["id"], "limits": dict(budget),
                "arms": arms,
            })
        if _graph_identity(graph) != initial_graph_identity:
            raise ValueError(task["id"] + ": delivery mutated source graph truth")
        first_arm = per_budget[0]["arms"][0]
        task_reports.append({
            "id": task["id"], "cohort": fixture_id,
            "intent_authored": task["intent"],
            "intent_detected_by_policy": task_channel(task["query"]),
            "query": task["query"],
            "source_basis": task["source_basis"],
            "calibration_only": bool(task.get("calibration_only")),
            "shared_activation": {
                "elapsed_ms": round(activation_ms, 3),
                "stage": activated_result.stage,
                "activated_nodes": len(activation.hits),
                "activated_edges": len(activation.edges),
                "source_node_ids": [hit.node.id for hit in activation.hits],
                "source_paths": sorted({
                    source_path(hit.node) for hit in activation.hits
                    if source_path(hit.node)
                }),
                "activated_required_files": [
                    row["file"] for row in first_arm["required_files"]
                    if row["activated"]
                ],
                "required_file_activation_recall": first_arm[
                    "required_file_activation_recall"
                ],
                "required_symbol_activation_recall": first_arm[
                    "required_symbol_activation_recall"
                ],
            },
            "budget_comparisons": per_budget,
        })
    result = {
        "schema": SCHEMA,
        "status": "measured_with_source_gaps",
        "frozen_manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "fixture_id": fixture_id,
        "source_revision": verified["source_revision"],
        "source_files_blobs_verified": verified["files_verified"],
        "source_graph_identity_sha256": initial_graph_identity,
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "graph_analysis_elapsed_ms": round(analysis_ms, 3),
        "policy_default_unchanged": True,
        "task_count": len(task_reports),
        "tasks": task_reports,
        "measurement_disclaimer": (
            "Known preauthored development/source controls, not independently "
            "held-out S7 tasks. Coarse file and named symbol visibility only; "
            "the actual source text and downstream LLM answers are not scored."
        ),
    }
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        manifest = load_frozen_manifest(Path(args.manifest))
        result = evaluate_fixture(
            manifest, args.fixture, Path(args.project_root).resolve(),
        )
        status = 0
    except Exception as exc:
        status = 1
        result = {
            "schema": SCHEMA, "status": "analysis_error",
            "fixture_id": args.fixture,
            "frozen_manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
            "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(),
        }
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(compact_json({
        "fixture_id": result.get("fixture_id"),
        "status": result["status"],
        "task_count": result.get("task_count"),
        "source_files_blobs_verified": result.get("source_files_blobs_verified"),
        "error": result.get("error"),
        "summary": [
            {
                "id": item["id"],
                "activation_file_recall": item["shared_activation"][
                    "required_file_activation_recall"
                ],
                "budgets": {
                    budget["id"]: [{
                        "arm": row["arm"], "file_recall": row["required_file_recall"],
                        "symbol_recall": row["required_symbol_recall"],
                        "test_recall": row["required_test_symbol_recall"],
                        "migration_recall": row["required_migration_symbol_recall"],
                        "distractor_approx_tokens": row[
                            "token_characters_by_source_role"
                        ]["preauthored_distractor_token_equivalent_approx"],
                        "nodes": row["nodes"], "tokens": row["estimated_context_tokens"],
                    } for row in budget["arms"]]
                    for budget in item["budget_comparisons"]
                },
            } for item in result.get("tasks", [])
        ],
    }))
    return status


if __name__ == "__main__":
    sys.exit(main())
