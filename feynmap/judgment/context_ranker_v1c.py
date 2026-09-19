"""Context Ranker v1C: candidate-budget sweep plus compact Jev state.

v1B remains frozen. v1C asks two separate questions:
1. How small can deterministic FeynMap retrieval become before golden recall drops?
2. How compact can provider state become while preserving Jev ranking quality?
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..context import ContextBudget, StoredSnapshotContext, estimate_tokens
from ..engine import FeynMapEngine
from ..snapshots import capture_repository_snapshot
from .contracts import JudgmentProvider, JudgmentQuestion, JudgmentResult
from .jev import JevJudgmentProvider
from .ranking import RankedCandidate, baseline_rank
from .real_benchmark import (
    _average,
    _candidate_label,
    _labels_for_source,
    _rank_labels,
    _ranking_metrics,
)

V1C_SCHEMA = "feynmap.context_ranker_v1c.v1"
FROZEN_RELEVANCE_PROMPT = (
    "Given task and grounded context, is candidate id %r relevant to completing the task? "
    "Judge only relevance; do not reinterpret graph evidence confidence."
)


def _compact_node(node: Mapping[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in ("id", "qualified_name", "name", "kind", "language", "framework", "confidence_tier"):
        value = node.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    location = node.get("location")
    if isinstance(location, Mapping):
        compact_location = {
            key: location[key]
            for key in ("path", "line")
            if key in location and location[key] is not None
        }
        if compact_location:
            compact["location"] = compact_location
    return compact


def _compact_relationships(
    root: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    root_id = str(root.get("id") or "")
    candidate_ids = {str(item.get("id")) for item in candidates if item.get("id")}
    keep_ids = candidate_ids | ({root_id} if root_id else set())
    compact: List[Dict[str, Any]] = []
    for edge in relationships:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in keep_ids or target not in keep_ids:
            continue
        # Prefer direct task-root structure. Candidate-to-candidate structure is
        # kept only when FeynMap retrieved it into the same bounded subgraph.
        if root_id and source != root_id and target != root_id:
            continue
        row = {
            key: edge[key]
            for key in ("source", "relationship", "target", "confidence_tier")
            if key in edge
        }
        compact.append(row)
    return compact


def build_compact_state(
    task: Mapping[str, Any],
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    root = bundle.get("root") or {}
    relationships = bundle.get("relationships") or []
    budget = bundle.get("budget") or {}
    return {
        "task": dict(task),
        "grounded_context": {
            "root": _compact_node(root) if isinstance(root, Mapping) else root,
            "candidates": [_compact_node(item) for item in candidates],
            "relationships": _compact_relationships(
                root if isinstance(root, Mapping) else {},
                candidates,
                relationships if isinstance(relationships, list) else [],
            ),
            "omissions": {
                key: budget.get(key)
                for key in ("omitted_nodes", "omitted_relationships", "truncated")
                if key in budget
            },
        },
    }


def build_v1b_style_state(
    task: Mapping[str, Any],
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Reconstruct the v1B provider payload for deterministic size comparison."""
    grounded = {
        "root": bundle.get("root"),
        "relationships": bundle.get("relationships"),
        "grounding": bundle.get("grounding"),
        "omissions": {
            key: (bundle.get("budget") or {}).get(key)
            for key in ("omitted_nodes", "omitted_relationships", "truncated")
        },
    }
    return {
        "task": dict(task),
        "candidates": [dict(item) for item in candidates],
        "grounded_context": grounded,
    }


def rerank_compact(
    task: Mapping[str, Any],
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    provider: JudgmentProvider,
) -> Tuple[List[RankedCandidate], Optional[JudgmentResult], Dict[str, Any]]:
    baseline = baseline_rank(candidates)
    if not baseline:
        return [], None, build_compact_state(task, bundle, candidates)

    state = build_compact_state(task, bundle, candidates)
    questions = {}
    key_to_id = {}
    for index, item in enumerate(baseline):
        key = "candidate_%d" % index
        key_to_id[key] = item.candidate_id
        questions[key] = JudgmentQuestion.noul(FROZEN_RELEVANCE_PROMPT % item.candidate_id)

    result = provider.evaluate(state, questions)
    probabilities: Dict[str, float] = {}
    for key, candidate_id in key_to_id.items():
        probability = float(result.answers[key].value)
        probabilities[candidate_id] = max(0.0, min(1.0, probability))

    ranked = [
        RankedCandidate(item.candidate, item.baseline_rank, probabilities[item.candidate_id])
        for item in baseline
    ]
    ranked.sort(
        key=lambda item: (
            -float(item.judgment_probability or 0.0),
            item.baseline_rank,
            item.candidate_id,
        )
    )
    return ranked, result, state


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != V1C_SCHEMA:
        raise ValueError("unsupported Context Ranker v1C schema")
    budgets = spec.get("candidate_budgets")
    if not isinstance(budgets, list) or not budgets:
        raise ValueError("v1C requires candidate_budgets")
    if any(not isinstance(value, int) or value <= 0 for value in budgets):
        raise ValueError("candidate_budgets must contain positive integers")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1C requires tasks")
    for task in tasks:
        if not isinstance(task, Mapping) or not task.get("id") or not task.get("root") or not task.get("description"):
            raise ValueError("each v1C task requires id, root, and description")


def run_graph_sweep(
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
    budgets = [int(value) for value in spec["candidate_budgets"]]

    budget_rows: List[Dict[str, Any]] = []
    for candidate_budget in budgets:
        task_rows: List[Dict[str, Any]] = []
        baseline_rows = []
        reranked_rows = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        elapsed = 0.0
        compact_estimate_total = 0
        full_estimate_total = 0

        for task in spec["tasks"]:
            bundle = context.context_bundle(
                str(task["root"]),
                depth=int(task.get("depth", depth)),
                budget=ContextBudget(
                    max_tokens=int(task.get("max_tokens", max_tokens)),
                    max_nodes=candidate_budget,
                    max_edges=int(task.get("max_edges", max_edges)),
                ),
            )
            candidates = list(bundle.get("nodes") or [])
            relevant, essential = _labels_for_source(golden, str(task["root"]))
            if not relevant:
                raise ValueError("task root has no frozen golden relationships: %s" % task["root"])

            baseline = baseline_rank(candidates)
            baseline_metrics = _ranking_metrics(baseline, relevant, essential, ks)
            baseline_rows.append(baseline_metrics)
            labels = set(_rank_labels(baseline))
            task_payload = {"description": task["description"]}
            compact_state = build_compact_state(task_payload, bundle, candidates)
            full_state = build_v1b_style_state(task_payload, bundle, candidates)
            compact_estimate = estimate_tokens(compact_state)
            full_estimate = estimate_tokens(full_state)
            compact_estimate_total += compact_estimate
            full_estimate_total += full_estimate

            row: Dict[str, Any] = {
                "id": task["id"],
                "root": task["root"],
                "candidate_count": len(candidates),
                "candidate_tokens": estimate_tokens(candidates),
                "bundle_tokens": (bundle.get("budget") or {}).get("estimated_tokens"),
                "retrieval": {
                    "relevant_recall": len(relevant & labels) / len(relevant) if relevant else None,
                    "essential_recall": len(essential & labels) / len(essential) if essential else None,
                    "missing_relevant": sorted(relevant - labels),
                    "missing_essential": sorted(essential - labels),
                },
                "baseline": baseline_metrics,
                "baseline_order": _rank_labels(baseline),
                "state_estimate": {
                    "v1b_style_tokens": full_estimate,
                    "compact_tokens": compact_estimate,
                    "token_reduction": (
                        1.0 - (compact_estimate / full_estimate) if full_estimate else None
                    ),
                },
            }

            if provider is not None and candidates:
                started = time.perf_counter()
                reranked, judgment, _ = rerank_compact(task_payload, bundle, candidates, provider)
                elapsed += time.perf_counter() - started
                reranked_metrics = _ranking_metrics(reranked, relevant, essential, ks)
                reranked_rows.append(reranked_metrics)
                row["reranked"] = reranked_metrics
                row["reranked_order"] = _rank_labels(reranked)
                row["probabilities"] = {
                    _candidate_label(item.candidate): item.judgment_probability
                    for item in reranked
                }
                if judgment is not None:
                    row["model"] = judgment.model
                    row["request_id"] = judgment.request_id
                    row["usage"] = dict(judgment.usage)
                    for key in usage:
                        value = judgment.usage.get(key)
                        if isinstance(value, (int, float)):
                            usage[key] += value
            task_rows.append(row)

        budget_result: Dict[str, Any] = {
            "candidate_budget": candidate_budget,
            "task_count": len(task_rows),
            "baseline": _average(baseline_rows),
            "tasks": task_rows,
            "estimated_state_tokens": {
                "v1b_style": full_estimate_total,
                "compact": compact_estimate_total,
                "reduction": (
                    1.0 - (compact_estimate_total / full_estimate_total)
                    if full_estimate_total
                    else None
                ),
            },
        }
        retrieval_relevant = [
            row["retrieval"]["relevant_recall"]
            for row in task_rows
            if row["retrieval"]["relevant_recall"] is not None
        ]
        retrieval_essential = [
            row["retrieval"]["essential_recall"]
            for row in task_rows
            if row["retrieval"]["essential_recall"] is not None
        ]
        budget_result["retrieval"] = {
            "mean_relevant_recall": (
                sum(retrieval_relevant) / len(retrieval_relevant) if retrieval_relevant else None
            ),
            "mean_essential_recall": (
                sum(retrieval_essential) / len(retrieval_essential) if retrieval_essential else None
            ),
            "tasks_with_full_relevant_recall": sum(value == 1.0 for value in retrieval_relevant),
            "tasks_with_full_essential_recall": sum(value == 1.0 for value in retrieval_essential),
        }
        if provider is not None:
            budget_result["provider"] = getattr(provider, "name", provider.__class__.__name__)
            budget_result["provider_elapsed_seconds"] = round(elapsed, 6)
            budget_result["usage"] = usage
            budget_result["reranked"] = _average(reranked_rows)
        budget_rows.append(budget_result)

    return {
        "schema": V1C_SCHEMA,
        "name": spec.get("name"),
        "snapshot_id": context.snapshot.snapshot_id,
        "repository_key": context.snapshot.repository_key,
        "candidate_budgets": budgets,
        "budgets": budget_rows,
    }


def run_repository_sweep(
    project_path: str,
    golden: Mapping[str, Any],
    spec: Mapping[str, Any],
    provider=None,
) -> Dict[str, Any]:
    root = Path(project_path).resolve()
    graph = FeynMapEngine().analyze(str(root))
    snapshot = capture_repository_snapshot(root, graph)
    return run_graph_sweep(StoredSnapshotContext(snapshot, graph), golden, spec, provider)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Context Ranker v1C candidate-budget and compact-state sweep"
    )
    parser.add_argument("project", help="Repository path to analyze")
    parser.add_argument(
        "--golden",
        default="feynmap/data/feynmap_golden.json",
        help="Frozen golden relationship JSON",
    )
    parser.add_argument(
        "--spec",
        default="experiments/context_ranker_v1c.json",
        help="v1C experiment specification",
    )
    parser.add_argument("--jev", action="store_true", help="Enable live compact-state Jev reranking")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    with open(args.golden, "r", encoding="utf-8") as handle:
        golden = json.load(handle)
    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    provider = JevJudgmentProvider() if args.jev else None
    result = run_repository_sweep(args.project, golden, spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
