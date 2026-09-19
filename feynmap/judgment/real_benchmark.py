"""Context Ranker v1B: real FeynMap retrieval against frozen graph annotations."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..context import ContextBudget, StoredSnapshotContext, estimate_tokens
from ..engine import FeynMapEngine
from ..snapshots import capture_repository_snapshot
from .jev import JevJudgmentProvider
from .ranking import RankedCandidate, baseline_rank, rerank_with_judgments_result

REAL_BENCHMARK_SCHEMA = "feynmap.context_ranker_real_benchmark.v1"


def _candidate_label(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("qualified_name") or candidate.get("id") or candidate.get("name") or "")


def _labels_for_source(golden: Mapping[str, Any], source: str) -> Tuple[Set[str], Set[str]]:
    relevant: Set[str] = set()
    essential: Set[str] = set()
    for row in golden.get("expected_relationships") or []:
        if not isinstance(row, Mapping) or row.get("source") != source:
            continue
        target = row.get("target")
        if not isinstance(target, str) or not target:
            continue
        relevant.add(target)
        if row.get("importance") == "critical":
            essential.add(target)
    return relevant, essential


def _rank_labels(ranked: Sequence[RankedCandidate]) -> List[str]:
    return [_candidate_label(item.candidate) for item in ranked]


def _dcg(order: Sequence[str], relevant: Set[str], essential: Set[str], k: int) -> float:
    score = 0.0
    for index, label in enumerate(order[:k], 1):
        gain = 2.0 if label in essential else (1.0 if label in relevant else 0.0)
        if gain:
            score += gain / math.log2(index + 1)
    return score


def _ranking_metrics(
    ranked: Sequence[RankedCandidate],
    relevant: Set[str],
    essential: Set[str],
    ks: Sequence[int],
) -> Dict[str, Any]:
    order = _rank_labels(ranked)
    payload: Dict[str, Any] = {}
    for k in ks:
        top = order[: max(0, int(k))]
        relevant_hits = sum(1 for label in top if label in relevant)
        essential_hits = sum(1 for label in top if label in essential)
        payload["precision@%d" % k] = relevant_hits / len(top) if top else None
        payload["relevant_recall@%d" % k] = relevant_hits / len(relevant) if relevant else None
        payload["essential_recall@%d" % k] = essential_hits / len(essential) if essential else None
        payload["noise@%d" % k] = (
            sum(1 for label in top if label not in relevant) / len(top) if top else None
        )
        ideal = sorted([2.0] * len(essential) + [1.0] * len(relevant - essential), reverse=True)
        ideal_dcg = sum(gain / math.log2(index + 1) for index, gain in enumerate(ideal[:k], 1))
        payload["ndcg@%d" % k] = (_dcg(order, relevant, essential, k) / ideal_dcg) if ideal_dcg else None

    relevant_ranks = [index for index, label in enumerate(order, 1) if label in relevant]
    precision_sum = 0.0
    seen = 0
    for index, label in enumerate(order, 1):
        if label in relevant:
            seen += 1
            precision_sum += seen / index
    payload["average_precision"] = precision_sum / len(relevant) if relevant else None
    payload["reciprocal_rank"] = (1.0 / relevant_ranks[0]) if relevant_ranks else 0.0

    missing_penalty = len(order) + 1
    essential_ranks = [
        (order.index(label) + 1) if label in order else missing_penalty
        for label in sorted(essential)
    ]
    payload["essential_mean_rank_penalized"] = (
        sum(essential_ranks) / len(essential_ranks) if essential_ranks else None
    )
    payload["missing_relevant"] = len(relevant - set(order))
    payload["missing_essential"] = len(essential - set(order))

    if essential and essential.issubset(set(order)):
        min_k = max(order.index(label) + 1 for label in essential)
        payload["essential_full_recall_min_k"] = min_k
        full_tokens = estimate_tokens([item.candidate for item in ranked])
        kept_tokens = estimate_tokens([item.candidate for item in ranked[:min_k]])
        payload["essential_context_token_ratio"] = kept_tokens / full_tokens if full_tokens else None
    else:
        payload["essential_full_recall_min_k"] = None
        payload["essential_context_token_ratio"] = None
    return payload


def _average(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Optional[float]]:
    keys = sorted({key for row in rows for key in row})
    result: Dict[str, Optional[float]] = {}
    for key in keys:
        values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
        result[key] = (sum(values) / len(values)) if values else None
    return result


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != REAL_BENCHMARK_SCHEMA:
        raise ValueError("unsupported real context-ranker benchmark schema")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("real benchmark requires tasks")
    for task in tasks:
        if not isinstance(task, Mapping) or not task.get("id") or not task.get("root") or not task.get("description"):
            raise ValueError("each task requires id, root, and description")


def run_graph_benchmark(
    context: StoredSnapshotContext,
    golden: Mapping[str, Any],
    spec: Mapping[str, Any],
    provider=None,
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, Any]:
    """Run ranking over candidates generated by FeynMap's real graph traversal."""
    _validate_spec(spec)
    task_rows: List[Dict[str, Any]] = []
    baseline_rows = []
    reranked_rows = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    provider_seconds = 0.0

    defaults = spec.get("retrieval") or {}
    for task in spec["tasks"]:
        depth = int(task.get("depth", defaults.get("depth", 3)))
        max_nodes = int(task.get("max_nodes", defaults.get("max_nodes", 40)))
        max_edges = int(task.get("max_edges", defaults.get("max_edges", 100)))
        max_tokens = int(task.get("max_tokens", defaults.get("max_tokens", 12000)))
        bundle = context.context_bundle(
            str(task["root"]),
            depth=depth,
            budget=ContextBudget(max_tokens=max_tokens, max_nodes=max_nodes, max_edges=max_edges),
        )
        candidates = list(bundle.get("nodes") or [])
        relevant, essential = _labels_for_source(golden, str(task["root"]))
        if not relevant:
            raise ValueError("task root has no frozen golden relationships: %s" % task["root"])

        baseline = baseline_rank(candidates)
        base_metrics = _ranking_metrics(baseline, relevant, essential, ks)
        baseline_rows.append(base_metrics)
        row: Dict[str, Any] = {
            "id": task["id"],
            "root": task["root"],
            "description": task["description"],
            "candidate_count": len(candidates),
            "candidate_tokens": estimate_tokens(candidates),
            "bundle_tokens": (bundle.get("budget") or {}).get("estimated_tokens"),
            "golden_relevant": sorted(relevant),
            "golden_essential": sorted(essential),
            "baseline_order": _rank_labels(baseline),
            "baseline": base_metrics,
            "retrieval": {
                "relevant_recall": (len(relevant & set(_rank_labels(baseline))) / len(relevant)) if relevant else None,
                "essential_recall": (len(essential & set(_rank_labels(baseline))) / len(essential)) if essential else None,
                "missing_relevant": sorted(relevant - set(_rank_labels(baseline))),
                "missing_essential": sorted(essential - set(_rank_labels(baseline))),
            },
        }

        if provider is not None and candidates:
            grounded = {
                "root": bundle.get("root"),
                "relationships": bundle.get("relationships"),
                "grounding": bundle.get("grounding"),
                "omissions": {
                    key: (bundle.get("budget") or {}).get(key)
                    for key in ("omitted_nodes", "omitted_relationships", "truncated")
                },
            }
            started = time.perf_counter()
            reranked, judgment = rerank_with_judgments_result(
                {"description": task["description"]},
                candidates,
                provider,
                shared_state=grounded,
            )
            provider_seconds += time.perf_counter() - started
            judged_metrics = _ranking_metrics(reranked, relevant, essential, ks)
            reranked_rows.append(judged_metrics)
            row["reranked_order"] = _rank_labels(reranked)
            row["reranked"] = judged_metrics
            row["probabilities"] = {
                _candidate_label(item.candidate): item.judgment_probability for item in reranked
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

    result: Dict[str, Any] = {
        "schema": REAL_BENCHMARK_SCHEMA,
        "name": spec.get("name"),
        "snapshot_id": context.snapshot.snapshot_id,
        "repository_key": context.snapshot.repository_key,
        "task_count": len(task_rows),
        "baseline": _average(baseline_rows),
        "tasks": task_rows,
    }
    if provider is not None:
        result["provider"] = getattr(provider, "name", provider.__class__.__name__)
        result["provider_elapsed_seconds"] = round(provider_seconds, 6)
        result["usage"] = usage
        result["reranked"] = _average(reranked_rows)
    return result


def run_repository_benchmark(
    project_path: str,
    golden: Mapping[str, Any],
    spec: Mapping[str, Any],
    provider=None,
) -> Dict[str, Any]:
    root = Path(project_path).resolve()
    graph = FeynMapEngine().analyze(str(root))
    snapshot = capture_repository_snapshot(root, graph)
    return run_graph_benchmark(StoredSnapshotContext(snapshot, graph), golden, spec, provider)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Context Ranker v1B on a real FeynMap repository graph")
    parser.add_argument("project", help="Repository path to analyze")
    parser.add_argument("--golden", default="feynmap/data/feynmap_golden.json", help="Frozen golden relationship JSON")
    parser.add_argument("--spec", default="experiments/context_ranker_v1b.json", help="Experiment task specification")
    parser.add_argument("--jev", action="store_true", help="Enable live Jev reranking")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    with open(args.golden, "r", encoding="utf-8") as handle:
        golden = json.load(handle)
    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    provider = JevJudgmentProvider() if args.jev else None
    result = run_repository_benchmark(args.project, golden, spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
