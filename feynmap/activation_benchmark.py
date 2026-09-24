"""S0 benchmark for FeynMap sparse knowledge activation.

The benchmark is intentionally retrieval-only. It measures how much of an
already-grounded semantic graph a search touches and activates, how much compact
context that activation represents, how long routing takes, and whether the
activated set reaches predeclared essential files/symbols.

It does not call a downstream LLM and therefore does not claim end-to-end answer
quality. Downstream task quality belongs to later S3/R1 benchmarks.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .activation import measure_guided_search
from .adaptive import AdaptiveSparseSearch
from .engine import FeynMapEngine
from .judgment.search import JevGuidedSearch
from .query import FeynMapQuery
from .routing import RegionFirstSearch

BENCHMARK_SCHEMA = "feynmap.sparse_activation_benchmark.v1"


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _node_paths(result) -> Set[str]:
    paths: Set[str] = set()
    for hit in result.hits:
        if hit.node.location and hit.node.location.path:
            paths.add(_normalize_path(hit.node.location.path))
    return paths


def _node_names(result) -> Set[str]:
    names: Set[str] = set()
    for hit in result.hits:
        node = hit.node
        names.add(node.id)
        names.add(node.name)
        if node.qualified_name:
            names.add(node.qualified_name)
    return names


def _matches_file(actual_paths: Iterable[str], expected: str) -> bool:
    target = _normalize_path(expected)
    for actual in actual_paths:
        normalized = _normalize_path(actual)
        if normalized == target or normalized.endswith("/" + target):
            return True
    return False


def _matches_symbol(actual_names: Set[str], expected: str) -> bool:
    return str(expected) in actual_names


def _graph_nodes_for_file(graph, expected: str):
    target = _normalize_path(expected)
    matches = []
    for node in graph.nodes:
        if not node.location or not node.location.path:
            continue
        path = _normalize_path(node.location.path)
        if path == target or path.endswith("/" + target):
            matches.append(node)
    return matches


def _shortest_graph_path(graph, start_id: str, target_ids: Set[str], max_depth: int = 8):
    if start_id in target_ids:
        return {"reachable": True, "depth": 0, "nodes": [start_id], "edges": []}

    queue = deque([(start_id, [])])
    seen = {start_id}
    while queue:
        current, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        edges = list(graph.outgoing(current)) + list(graph.incoming(current))
        edges.sort(key=lambda edge: (edge.kind.value, edge.source, edge.target, edge.id))
        for edge in edges:
            # Repository-root containment is useful for graph ownership but is
            # not evidence that two application concepts are semantically
            # related. Exclude it from reachability diagnosis so the reported
            # path reflects actual calls/imports/integration/composition.
            if edge.kind.value == "contains" and "repository:root" in {edge.source, edge.target}:
                continue
            neighbor = edge.target if edge.source == current else edge.source
            if neighbor in seen:
                continue
            next_path = path + [edge]
            if neighbor in target_ids:
                node_ids = [start_id]
                cursor = start_id
                for item in next_path:
                    cursor = item.target if item.source == cursor else item.source
                    node_ids.append(cursor)
                return {
                    "reachable": True,
                    "depth": len(next_path),
                    "nodes": node_ids,
                    "edges": [
                        {
                            "id": item.id,
                            "kind": item.kind.value,
                            "source": item.source,
                            "target": item.target,
                        }
                        for item in next_path
                    ],
                }
            seen.add(neighbor)
            queue.append((neighbor, next_path))
    return {"reachable": False, "depth": None, "nodes": [], "edges": []}


def _essential_file_diagnostics(
    graph,
    task: Mapping[str, Any],
    files: Sequence[str],
    search_result=None,
) -> Dict[str, Any]:
    root_id = None
    if task.get("mode", "concept") == "node" and task.get("root"):
        try:
            root_id = FeynMapQuery(graph).resolve(str(task["root"])).id
        except KeyError:
            root_id = None

    diagnostics: Dict[str, Any] = {}
    for expected in files:
        nodes = _graph_nodes_for_file(graph, expected)
        payload: Dict[str, Any] = {
            "graph_node_ids": [node.id for node in nodes],
            "present_in_graph": bool(nodes),
        }
        target_ids = {node.id for node in nodes}
        if search_result is not None and target_ids:
            payload["search_trace"] = [
                {
                    "depth": step.depth,
                    "candidate": bool(target_ids.intersection(step.candidates)),
                    "selected": bool(target_ids.intersection(step.selected)),
                    "candidate_count": len(step.candidates),
                    "selected_count": len(step.selected),
                }
                for step in search_result.trace
                if target_ids.intersection(step.candidates) or target_ids.intersection(step.selected)
            ]
        if root_id and nodes:
            payload["path_from_root"] = _shortest_graph_path(
                graph,
                root_id,
                target_ids,
            )
        elif root_id:
            payload["path_from_root"] = {
                "reachable": False,
                "depth": None,
                "nodes": [],
                "edges": [],
            }
        diagnostics[expected] = payload
    return diagnostics


def _average(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    return sum(values) / len(values)


def validate_dataset(dataset: Mapping[str, Any]) -> None:
    if dataset.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("unsupported sparse activation benchmark schema")
    tasks = dataset.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("benchmark requires a non-empty tasks list")
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("each task must be an object")
        if not task.get("id") or not task.get("query"):
            raise ValueError("each task requires id and query")
        mode = str(task.get("mode", "concept"))
        if mode not in {"concept", "node"}:
            raise ValueError("task mode must be concept or node")
        if mode == "node" and not task.get("root"):
            raise ValueError("node-mode tasks require root")
        if not (task.get("essential_files") or task.get("essential_symbols")):
            raise ValueError("each task requires essential_files and/or essential_symbols")


def _search_kwargs(task: Mapping[str, Any]) -> Dict[str, Any]:
    configured = task.get("search") or {}
    if not isinstance(configured, Mapping):
        raise ValueError("task search settings must be an object")
    allowed = {
        "max_depth",
        "beam_width",
        "max_nodes",
        "direction",
        "seed_limit",
        "candidate_limit",
    }
    return {key: configured[key] for key in allowed if key in configured}


def run_benchmark(
    project_root: str,
    dataset: Mapping[str, Any],
    provider=None,
    *,
    strategy: str = "flat",
    region_limit: int = 8,
    region_seed_limit: int = 12,
) -> Dict[str, Any]:
    validate_dataset(dataset)
    analysis = dataset.get("analysis") or {}
    if not isinstance(analysis, Mapping):
        raise ValueError("analysis settings must be an object")

    language = str(analysis.get("language", "auto"))
    framework = str(analysis.get("framework", "auto"))

    analysis_started = time.perf_counter()
    graph = FeynMapEngine().analyze(project_root, language=language, framework=framework)
    analysis_elapsed_ms = (time.perf_counter() - analysis_started) * 1000.0

    strategy = str(strategy).strip().lower()
    if strategy not in {"flat", "region", "adaptive"}:
        raise ValueError("strategy must be flat, region, or adaptive")

    searcher = JevGuidedSearch(graph, provider=provider)
    region_searcher = (
        RegionFirstSearch(
            graph,
            provider=provider,
            region_limit=region_limit,
            seed_limit=region_seed_limit,
        )
        if strategy == "region"
        else None
    )
    adaptive_searcher = (
        AdaptiveSparseSearch(
            graph,
            provider=provider,
            region_limit=region_limit,
            region_seed_limit=region_seed_limit,
        )
        if strategy == "adaptive"
        else None
    )
    task_rows: List[Dict[str, Any]] = []

    for task in dataset["tasks"]:
        mode = str(task.get("mode", "concept"))
        query = str(task["query"])
        kwargs = _search_kwargs(task)

        search_started = time.perf_counter()
        route_payload = None
        adaptive_payload = None
        if mode == "node":
            # seed_limit/candidate_limit apply only to concept mode.
            node_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key not in {"seed_limit", "candidate_limit"}
            }
            if adaptive_searcher is not None:
                adaptive_result = adaptive_searcher.from_node(
                    str(task["root"]),
                    query,
                    **node_kwargs
                )
                result = adaptive_result.search
                route_payload = (
                    adaptive_result.route.to_dict()
                    if adaptive_result.route is not None
                    else None
                )
                adaptive_payload = {
                    "stage": adaptive_result.stage,
                    "escalations": list(adaptive_result.escalations),
                    "local_sufficiency": adaptive_result.local_sufficiency.to_dict(),
                    "final_sufficiency": adaptive_result.final_sufficiency.to_dict(),
                    "timings_ms": dict(adaptive_result.timings_ms),
                }
            elif region_searcher is not None:
                region_result = region_searcher.from_node(str(task["root"]), query, **node_kwargs)
                result = region_result.search
                route_payload = region_result.route.to_dict()
            else:
                result = searcher.from_node(str(task["root"]), query, **node_kwargs)
        else:
            if adaptive_searcher is not None:
                adaptive_result = adaptive_searcher.concept(query, **kwargs)
                result = adaptive_result.search
                route_payload = adaptive_result.route.to_dict()
                adaptive_payload = {
                    "stage": adaptive_result.stage,
                    "escalations": list(adaptive_result.escalations),
                    "local_sufficiency": adaptive_result.local_sufficiency.to_dict(),
                    "final_sufficiency": adaptive_result.final_sufficiency.to_dict(),
                }
            elif region_searcher is not None:
                region_result = region_searcher.concept(query, **kwargs)
                result = region_result.search
                route_payload = region_result.route.to_dict()
            else:
                result = searcher.concept(query, **kwargs)
        routing_elapsed_ms = (time.perf_counter() - search_started) * 1000.0

        metrics = measure_guided_search(
            graph,
            result,
            routing_elapsed_seconds=routing_elapsed_ms / 1000.0,
        )

        actual_paths = _node_paths(result)
        actual_names = _node_names(result)
        essential_files = [_normalize_path(item) for item in task.get("essential_files") or []]
        essential_symbols = [str(item) for item in task.get("essential_symbols") or []]
        retrievable_files = [
            item for item in essential_files
            if (Path(project_root) / item).exists()
        ]
        unretrievable_files = [
            item for item in essential_files
            if item not in retrievable_files
        ]

        matched_files = [item for item in retrievable_files if _matches_file(actual_paths, item)]
        matched_symbols = [item for item in essential_symbols if _matches_symbol(actual_names, item)]
        total_essential = len(retrievable_files) + len(essential_symbols)
        total_matched = len(matched_files) + len(matched_symbols)
        essential_recall = (float(total_matched) / float(total_essential)) if total_essential else None

        task_rows.append(
            {
                "id": task["id"],
                "mode": mode,
                "query": query,
                "root": task.get("root"),
                "revision": task.get("revision"),
                "strategy": strategy,
                "region_route": route_payload,
                "adaptive": adaptive_payload,
                "metrics": metrics.to_dict(),
                "essential_recall": essential_recall,
                "essential_full_recall": bool(total_essential and total_matched == total_essential),
                "essential_files": essential_files,
                "retrievable_essential_files": retrievable_files,
                "unretrievable_essential_files": unretrievable_files,
                "matched_essential_files": matched_files,
                "missing_essential_files": [item for item in retrievable_files if item not in matched_files],
                "essential_file_diagnostics": _essential_file_diagnostics(graph, task, retrievable_files, result),
                "essential_symbols": essential_symbols,
                "matched_essential_symbols": matched_symbols,
                "missing_essential_symbols": [item for item in essential_symbols if item not in matched_symbols],
                "activated_files": sorted(actual_paths),
                "activated_node_ids": [hit.node.id for hit in result.hits],
            }
        )

    metric_rows = [row["metrics"] for row in task_rows]
    return {
        "schema": BENCHMARK_SCHEMA,
        "name": dataset.get("name"),
        "repository": dataset.get("repository"),
        "project_root": os.path.basename(os.path.abspath(project_root)),
        "strategy": strategy,
        "routing_config": {
            "region_limit": int(region_limit) if strategy == "region" else None,
            "region_seed_limit": int(region_seed_limit) if strategy == "region" else None,
        },
        "analysis": {
            "language": language,
            "framework": framework,
            "elapsed_ms": round(analysis_elapsed_ms, 6),
            "graph_nodes": len(graph.nodes),
            "graph_edges": len(graph.edges),
            "diagnostics": graph.diagnostics,
        },
        "task_count": len(task_rows),
        "summary": {
            "mean_candidate_touch_ratio": _average(metric_rows, "candidate_touch_ratio"),
            "mean_knowledge_activation_ratio": _average(metric_rows, "knowledge_activation_ratio"),
            "mean_routing_elapsed_ms": _average(metric_rows, "routing_elapsed_ms"),
            "mean_activated_context_tokens": _average(metric_rows, "activated_context_tokens"),
            "mean_essential_recall": _average(task_rows, "essential_recall"),
            "full_recall_tasks": sum(1 for row in task_rows if row["essential_full_recall"]),
            "mean_region_touch_ratio": _average(
                [row["region_route"] for row in task_rows if row.get("region_route")],
                "region_touch_ratio",
            ),
            "local_stop_tasks": sum(
                1
                for row in task_rows
                if (row.get("adaptive") or {}).get("stage") == "local"
            ),
            "region_escalation_tasks": sum(
                1
                for row in task_rows
                if "region" in ((row.get("adaptive") or {}).get("escalations") or [])
            ),
            "jev_escalation_tasks": sum(
                1
                for row in task_rows
                if "jev" in ((row.get("adaptive") or {}).get("escalations") or [])
            ),
            "mean_local_sufficiency_score": _average(
                [
                    row["adaptive"]["local_sufficiency"]
                    for row in task_rows
                    if row.get("adaptive")
                ],
                "score",
            ),
        },
        "tasks": task_rows,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run FeynMap sparse-activation S0 benchmark")
    parser.add_argument("dataset", help="Path to feynmap.sparse_activation_benchmark.v1 JSON")
    parser.add_argument("project_root", help="Repository root to analyze")
    parser.add_argument("--output", help="Optional path for the JSON result")
    parser.add_argument("--task", action="append", dest="tasks", help="Run only the named task id; repeatable")
    parser.add_argument("--strategy", choices=("flat", "region", "adaptive"), default="flat")
    parser.add_argument("--region-limit", type=int, default=8)
    parser.add_argument("--region-seed-limit", type=int, default=12)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    with open(args.dataset, "r", encoding="utf-8") as handle:
        dataset = json.load(handle)

    if args.tasks:
        requested = set(args.tasks)
        available = {str(task.get("id")) for task in dataset.get("tasks") or []}
        missing = sorted(requested - available)
        if missing:
            raise ValueError("unknown benchmark task(s): %s" % ", ".join(missing))
        dataset = dict(dataset)
        dataset["tasks"] = [
            task for task in dataset["tasks"] if str(task.get("id")) in requested
        ]

    result = run_benchmark(
        args.project_root,
        dataset,
        strategy=args.strategy,
        region_limit=args.region_limit,
        region_seed_limit=args.region_seed_limit,
    )
    rendered = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
