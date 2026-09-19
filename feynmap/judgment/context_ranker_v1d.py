"""Context Ranker v1D: adaptive structural retrieval cutoff.

v1B and v1C remain frozen. v1D replaces a fixed candidate count with a
language-agnostic structural stopping rule: retrieve until the root's direct
outgoing behavioral targets are covered, bounded by a safety floor/ceiling.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..context import ContextBudget, StoredSnapshotContext, estimate_tokens
from ..core import EdgeKind
from ..engine import FeynMapEngine
from ..snapshots import capture_repository_snapshot
from .context_ranker_v1c import build_compact_state, rerank_compact
from .jev import JevJudgmentProvider
from .ranking import baseline_rank
from .real_benchmark import _average, _labels_for_source, _rank_labels, _ranking_metrics

V1D_SCHEMA = "feynmap.context_ranker_v1d.v1"

# Structural/container relationships do not by themselves imply that the target
# participates in the root's behavior. Everything else in the canonical
# ontology is treated as behavioral for this experiment.
NON_BEHAVIORAL_KINDS = {
    EdgeKind.CONTAINS,
    EdgeKind.OWNS,
    EdgeKind.IMPORTS,
    EdgeKind.RELATED_TO,
}


def _behavioral_targets(context: StoredSnapshotContext, root_id: str) -> Dict[str, List[str]]:
    by_kind: Dict[str, List[str]] = {}
    for edge in context.graph.outgoing(root_id):
        if edge.kind in NON_BEHAVIORAL_KINDS:
            continue
        if edge.target == root_id:
            continue
        by_kind.setdefault(edge.kind.value, []).append(edge.target)
    for kind in by_kind:
        by_kind[kind] = sorted(set(by_kind[kind]))
    return dict(sorted(by_kind.items()))


def adaptive_cutoff(
    context: StoredSnapshotContext,
    root_symbol: str,
    pool_candidates: Sequence[Mapping[str, Any]],
    *,
    minimum: int,
    ceiling: int,
) -> Dict[str, Any]:
    """Choose the smallest prefix covering direct outgoing behavioral targets."""
    root = context.query.resolve(root_symbol)
    by_kind = _behavioral_targets(context, root.id)
    required: Set[str] = {target for values in by_kind.values() for target in values}
    order = [str(candidate.get("id") or "") for candidate in pool_candidates]
    position = {candidate_id: index for index, candidate_id in enumerate(order, 1) if candidate_id}

    covered = sorted(required & set(position))
    missing = sorted(required - set(position))
    last_required_rank = max((position[target] for target in covered), default=0)

    effective_ceiling = max(1, int(ceiling))
    effective_minimum = min(effective_ceiling, max(1, int(minimum)))
    saturated = bool(missing)
    cutoff = effective_ceiling if saturated else max(effective_minimum, last_required_rank)
    cutoff = min(effective_ceiling, cutoff)

    return {
        "cutoff": cutoff,
        "minimum": effective_minimum,
        "ceiling": effective_ceiling,
        "last_required_rank": last_required_rank or None,
        "behavioral_target_count": len(required),
        "behavioral_targets_by_kind": by_kind,
        "covered_behavioral_targets": covered,
        "missing_behavioral_targets": missing,
        "behavioral_coverage": (len(covered) / len(required)) if required else 1.0,
        "saturated": saturated,
        "rule": "smallest candidate prefix covering all direct outgoing behavioral targets, bounded by minimum/ceiling",
    }


def _bundle(
    context: StoredSnapshotContext,
    root: str,
    *,
    depth: int,
    max_nodes: int,
    max_edges: int,
    max_tokens: int,
) -> Dict[str, Any]:
    return context.context_bundle(
        root,
        depth=depth,
        budget=ContextBudget(
            max_tokens=max_tokens,
            max_nodes=max_nodes,
            max_edges=max_edges,
        ),
    )


def _retrieval_metrics(candidates, relevant, essential):
    labels = set(_rank_labels(baseline_rank(candidates)))
    return {
        "relevant_recall": len(relevant & labels) / len(relevant) if relevant else None,
        "essential_recall": len(essential & labels) / len(essential) if essential else None,
        "missing_relevant": sorted(relevant - labels),
        "missing_essential": sorted(essential - labels),
    }


def _run_selection(
    context: StoredSnapshotContext,
    task: Mapping[str, Any],
    relevant,
    essential,
    *,
    candidate_budget: int,
    depth: int,
    max_edges: int,
    max_tokens: int,
    provider=None,
    ks: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, Any]:
    bundle = _bundle(
        context,
        str(task["root"]),
        depth=depth,
        max_nodes=candidate_budget,
        max_edges=max_edges,
        max_tokens=max_tokens,
    )
    candidates = list(bundle.get("nodes") or [])
    baseline = baseline_rank(candidates)
    row: Dict[str, Any] = {
        "candidate_budget": candidate_budget,
        "candidate_count": len(candidates),
        "candidate_tokens": estimate_tokens(candidates),
        "bundle_tokens": (bundle.get("budget") or {}).get("estimated_tokens"),
        "retrieval": _retrieval_metrics(candidates, relevant, essential),
        "baseline": _ranking_metrics(baseline, relevant, essential, ks),
        "baseline_order": _rank_labels(baseline),
        "compact_state_tokens": estimate_tokens(
            build_compact_state({"description": task["description"]}, bundle, candidates)
        ),
    }
    if provider is not None and candidates:
        started = time.perf_counter()
        reranked, judgment, _ = rerank_compact(
            {"description": task["description"]},
            bundle,
            candidates,
            provider,
        )
        row["provider_elapsed_seconds"] = round(time.perf_counter() - started, 6)
        row["reranked"] = _ranking_metrics(reranked, relevant, essential, ks)
        row["reranked_order"] = _rank_labels(reranked)
        if judgment is not None:
            row["usage"] = dict(judgment.usage)
            row["model"] = judgment.model
            row["request_id"] = judgment.request_id
    return row


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != V1D_SCHEMA:
        raise ValueError("unsupported Context Ranker v1D schema")
    adaptive = spec.get("adaptive") or {}
    minimum = adaptive.get("minimum_candidates")
    ceiling = adaptive.get("maximum_candidates")
    if not isinstance(minimum, int) or minimum <= 0:
        raise ValueError("adaptive.minimum_candidates must be a positive integer")
    if not isinstance(ceiling, int) or ceiling < minimum:
        raise ValueError("adaptive.maximum_candidates must be >= minimum_candidates")
    budgets = spec.get("comparison_budgets")
    if not isinstance(budgets, list) or not budgets:
        raise ValueError("v1D requires comparison_budgets")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1D requires tasks")


def run_graph_experiment(
    context: StoredSnapshotContext,
    golden: Mapping[str, Any],
    spec: Mapping[str, Any],
    provider=None,
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, Any]:
    _validate_spec(spec)
    retrieval = spec.get("retrieval") or {}
    depth = int(retrieval.get("depth", 3))
    max_edges = int(retrieval.get("max_edges", 100))
    max_tokens = int(retrieval.get("max_tokens", 12000))
    adaptive_spec = spec["adaptive"]
    minimum = int(adaptive_spec["minimum_candidates"])
    ceiling = int(adaptive_spec["maximum_candidates"])
    comparison_budgets = [int(value) for value in spec["comparison_budgets"]]
    jev_comparators = set(int(value) for value in spec.get("jev_comparison_budgets", [10]))

    task_rows: List[Dict[str, Any]] = []
    for task in spec["tasks"]:
        relevant, essential = _labels_for_source(golden, str(task["root"]))
        if not relevant:
            raise ValueError("task root has no frozen golden relationships: %s" % task["root"])

        pool_bundle = _bundle(
            context,
            str(task["root"]),
            depth=depth,
            max_nodes=ceiling,
            max_edges=max_edges,
            max_tokens=max_tokens,
        )
        pool_candidates = list(pool_bundle.get("nodes") or [])
        decision = adaptive_cutoff(
            context,
            str(task["root"]),
            pool_candidates,
            minimum=minimum,
            ceiling=ceiling,
        )

        adaptive_row = _run_selection(
            context,
            task,
            relevant,
            essential,
            candidate_budget=int(decision["cutoff"]),
            depth=depth,
            max_edges=max_edges,
            max_tokens=max_tokens,
            provider=provider,
            ks=ks,
        )
        adaptive_row["decision"] = decision

        fixed_rows = []
        for budget in comparison_budgets:
            fixed_rows.append(
                _run_selection(
                    context,
                    task,
                    relevant,
                    essential,
                    candidate_budget=budget,
                    depth=depth,
                    max_edges=max_edges,
                    max_tokens=max_tokens,
                    provider=provider if budget in jev_comparators else None,
                    ks=ks,
                )
            )
        task_rows.append(
            {
                "id": task["id"],
                "root": task["root"],
                "description": task["description"],
                "adaptive": adaptive_row,
                "fixed": fixed_rows,
            }
        )

    adaptive_baseline = [row["adaptive"]["baseline"] for row in task_rows]
    adaptive_reranked = [
        row["adaptive"]["reranked"] for row in task_rows if "reranked" in row["adaptive"]
    ]
    cutoffs = [row["adaptive"]["candidate_budget"] for row in task_rows]
    adaptive_relevant = [
        row["adaptive"]["retrieval"]["relevant_recall"]
        for row in task_rows
        if row["adaptive"]["retrieval"]["relevant_recall"] is not None
    ]
    adaptive_essential = [
        row["adaptive"]["retrieval"]["essential_recall"]
        for row in task_rows
        if row["adaptive"]["retrieval"]["essential_recall"] is not None
    ]
    result: Dict[str, Any] = {
        "schema": V1D_SCHEMA,
        "name": spec.get("name"),
        "snapshot_id": context.snapshot.snapshot_id,
        "repository_key": context.snapshot.repository_key,
        "adaptive_summary": {
            "mean_candidate_count": sum(cutoffs) / len(cutoffs) if cutoffs else None,
            "min_candidate_count": min(cutoffs) if cutoffs else None,
            "max_candidate_count": max(cutoffs) if cutoffs else None,
            "mean_relevant_recall": (
                sum(adaptive_relevant) / len(adaptive_relevant) if adaptive_relevant else None
            ),
            "mean_essential_recall": (
                sum(adaptive_essential) / len(adaptive_essential) if adaptive_essential else None
            ),
            "baseline": _average(adaptive_baseline),
        },
        "tasks": task_rows,
    }
    if adaptive_reranked:
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        elapsed = 0.0
        for row in task_rows:
            adaptive = row["adaptive"]
            elapsed += float(adaptive.get("provider_elapsed_seconds") or 0.0)
            for key in total_usage:
                value = (adaptive.get("usage") or {}).get(key)
                if isinstance(value, (int, float)):
                    total_usage[key] += value
        result["adaptive_summary"]["reranked"] = _average(adaptive_reranked)
        result["adaptive_summary"]["usage"] = total_usage
        result["adaptive_summary"]["provider_elapsed_seconds"] = round(elapsed, 6)

    # Aggregate fixed retrieval so the adaptive rule can be compared to every
    # fixed budget without using Jev for all of them.
    fixed_summary = []
    for budget in comparison_budgets:
        matching = []
        for task_row in task_rows:
            matching.extend(row for row in task_row["fixed"] if row["candidate_budget"] == budget)
        relevant_values = [
            row["retrieval"]["relevant_recall"]
            for row in matching
            if row["retrieval"]["relevant_recall"] is not None
        ]
        essential_values = [
            row["retrieval"]["essential_recall"]
            for row in matching
            if row["retrieval"]["essential_recall"] is not None
        ]
        entry: Dict[str, Any] = {
            "candidate_budget": budget,
            "mean_relevant_recall": (
                sum(relevant_values) / len(relevant_values) if relevant_values else None
            ),
            "mean_essential_recall": (
                sum(essential_values) / len(essential_values) if essential_values else None
            ),
            "baseline": _average([row["baseline"] for row in matching]),
            "mean_compact_state_tokens": (
                sum(row["compact_state_tokens"] for row in matching) / len(matching)
                if matching else None
            ),
        }
        reranked = [row["reranked"] for row in matching if "reranked" in row]
        if reranked:
            entry["reranked"] = _average(reranked)
            usage = {"input_tokens": 0, "output_tokens": 0}
            for row in matching:
                for key in usage:
                    value = (row.get("usage") or {}).get(key)
                    if isinstance(value, (int, float)):
                        usage[key] += value
            entry["usage"] = usage
        fixed_summary.append(entry)
    result["fixed_summary"] = fixed_summary
    return result


def run_repository_experiment(
    project_path: str,
    golden: Mapping[str, Any],
    spec: Mapping[str, Any],
    provider=None,
) -> Dict[str, Any]:
    root = Path(project_path).resolve()
    graph = FeynMapEngine().analyze(str(root))
    snapshot = capture_repository_snapshot(root, graph)
    return run_graph_experiment(StoredSnapshotContext(snapshot, graph), golden, spec, provider)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Context Ranker v1D adaptive-cutoff experiment")
    parser.add_argument("project", help="Repository path to analyze")
    parser.add_argument("--golden", default="feynmap/data/feynmap_golden.json")
    parser.add_argument("--spec", default="experiments/context_ranker_v1d.json")
    parser.add_argument("--jev", action="store_true", help="Run Jev for adaptive and configured fixed comparator")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with open(args.golden, "r", encoding="utf-8") as handle:
        golden = json.load(handle)
    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    provider = JevJudgmentProvider() if args.jev else None
    result = run_repository_experiment(args.project, golden, spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
