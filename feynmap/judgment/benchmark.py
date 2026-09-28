"""Reproducible Context Ranker v1 benchmark harness."""
from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .jev import JevJudgmentProvider
from .ranking import RankedCandidate, baseline_rank, rerank_with_judgments_result

BENCHMARK_SCHEMA = "feynmap.context_ranker_benchmark.v1"


def _ids(ranked: Sequence[RankedCandidate]) -> List[str]:
    return [item.candidate_id for item in ranked]


def _metrics(
    ranked: Sequence[RankedCandidate],
    relevant: Iterable[str],
    essential: Iterable[str],
    ks: Sequence[int],
) -> Dict[str, Any]:
    order = _ids(ranked)
    relevant_set = set(relevant)
    essential_set = set(essential)
    payload: Dict[str, Any] = {}
    for k in ks:
        top = order[: max(0, int(k))]
        hits = sum(1 for candidate_id in top if candidate_id in relevant_set)
        payload["precision@%d" % k] = hits / len(top) if top else None
        payload["relevant_recall@%d" % k] = hits / len(relevant_set) if relevant_set else None
        essential_hits = sum(1 for candidate_id in top if candidate_id in essential_set)
        payload["essential_recall@%d" % k] = essential_hits / len(essential_set) if essential_set else None
    first_relevant = next((index for index, candidate_id in enumerate(order, 1) if candidate_id in relevant_set), None)
    payload["reciprocal_rank"] = (1.0 / first_relevant) if first_relevant else 0.0
    return payload


def _average(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Optional[float]]:
    keys = sorted({key for row in rows for key in row})
    result: Dict[str, Optional[float]] = {}
    for key in keys:
        values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
        result[key] = (sum(values) / len(values)) if values else None
    return result


def validate_dataset(dataset: Mapping[str, Any]) -> None:
    if dataset.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("unsupported context ranker benchmark schema")
    tasks = dataset.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("benchmark requires a non-empty tasks list")
    for task in tasks:
        if not isinstance(task, Mapping) or not task.get("id") or not task.get("description"):
            raise ValueError("each benchmark task requires id and description")
        candidates = task.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("each benchmark task requires candidates")
        ids = [candidate.get("id") for candidate in candidates if isinstance(candidate, Mapping)]
        if len(ids) != len(candidates) or any(not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("candidate ids must be non-empty and unique within a task")
        known = set(ids)
        relevant = set(task.get("relevant") or [])
        essential = set(task.get("essential") or [])
        if not relevant.issubset(known) or not essential.issubset(relevant):
            raise ValueError("essential must be a subset of relevant, and labels must name candidates")


def run_benchmark(dataset: Mapping[str, Any], provider=None, *, ks: Sequence[int] = (1, 3, 5)) -> Dict[str, Any]:
    validate_dataset(dataset)
    task_rows: List[Dict[str, Any]] = []
    baseline_metrics = []
    reranked_metrics = []
    total_usage = {"input_tokens": 0, "output_tokens": 0}
    provider_seconds = 0.0
    request_ids = []

    for task in dataset["tasks"]:
        baseline = baseline_rank(task["candidates"])
        base = _metrics(baseline, task.get("relevant") or [], task.get("essential") or [], ks)
        baseline_metrics.append(base)
        row: Dict[str, Any] = {
            "id": task["id"],
            "baseline_order": _ids(baseline),
            "baseline": base,
            "candidate_count": len(baseline),
        }

        if provider is not None:
            started = time.perf_counter()
            reranked, judgment = rerank_with_judgments_result(
                {"description": task["description"]},
                task["candidates"],
                provider,
                shared_state=task.get("context"),
            )
            provider_seconds += time.perf_counter() - started
            judged = _metrics(reranked, task.get("relevant") or [], task.get("essential") or [], ks)
            reranked_metrics.append(judged)
            row["reranked_order"] = _ids(reranked)
            row["reranked"] = judged
            row["probabilities"] = {item.candidate_id: item.judgment_probability for item in reranked}
            if judgment is not None:
                row["provider"] = judgment.provider
                row["model"] = judgment.model
                row["usage"] = dict(judgment.usage)
                if judgment.request_id:
                    row["request_id"] = judgment.request_id
                    request_ids.append(judgment.request_id)
                for key in total_usage:
                    value = judgment.usage.get(key)
                    if isinstance(value, (int, float)):
                        total_usage[key] += value
        task_rows.append(row)

    result: Dict[str, Any] = {
        "schema": BENCHMARK_SCHEMA,
        "name": dataset.get("name"),
        "task_count": len(task_rows),
        "baseline": _average(baseline_metrics),
        "tasks": task_rows,
    }
    if provider is not None:
        result["reranked"] = _average(reranked_metrics)
        result["provider"] = getattr(provider, "name", provider.__class__.__name__)
        result["provider_elapsed_seconds"] = round(provider_seconds, 6)
        result["usage"] = total_usage
        result["request_ids"] = request_ids
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the FeynMap Context Ranker v1 benchmark")
    parser.add_argument("dataset", help="Path to a context ranker benchmark JSON file")
    parser.add_argument("--jev", action="store_true", help="Enable live Jev reranking")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)
    with open(args.dataset, "r", encoding="utf-8") as handle:
        dataset = json.load(handle)
    provider = JevJudgmentProvider() if args.jev else None
    result = run_benchmark(dataset, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
