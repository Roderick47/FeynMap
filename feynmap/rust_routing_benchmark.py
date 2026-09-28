"""S6.4.3 benchmark for the first Rust acceleration target.

The benchmark isolates RegionIndex.route() after repository analysis and index
construction. It establishes the Python reference baseline that a future Rust
implementation must beat without changing routing semantics.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .engine import FeynMapEngine
from .query import FeynMapQuery
from .routing import RegionIndex
from .rust_routing_boundary import (
    RUST_ROUTING_BOUNDARY_VERSION,
    prepare_region_routing_index,
    route_through_compact_python_boundary,
)


BENCHMARK_SCHEMA = "feynmap.rust_region_routing_benchmark.v1"


def validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("unsupported Rust routing benchmark schema")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Rust routing benchmark requires tasks")
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("each Rust routing benchmark task must be an object")
        if not task.get("id") or not task.get("query"):
            raise ValueError("each Rust routing task requires id and query")
    for field in ("warmup_rounds", "measurement_rounds", "region_limit"):
        value = spec.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("%s must be a positive integer" % field)


def _load_json(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark spec must contain a JSON object")
    return payload


def _prepared_tasks(
    graph,
    tasks: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    query = FeynMapQuery(graph)
    prepared: List[Dict[str, Any]] = []
    for task in tasks:
        root = task.get("root")
        anchor_node_id = None
        if root:
            anchor_node_id = query.resolve(str(root)).id
        prepared.append(
            {
                "id": str(task["id"]),
                "query": str(task["query"]),
                "root": str(root) if root else None,
                "anchor_node_id": anchor_node_id,
            }
        )
    return prepared


def _route_signature(route) -> Dict[str, Any]:
    return {
        "anchor_region": route.anchor_region,
        "candidate_regions": int(route.candidate_regions),
        "selected_regions": list(route.selected_regions),
        "scores": {
            key: round(float(value), 12)
            for key, value in sorted(route.scores.items())
        },
    }


def run_benchmark(
    project_root: str,
    spec: Mapping[str, Any],
) -> Dict[str, Any]:
    validate_spec(spec)
    root = Path(project_root).resolve()
    analysis = spec.get("analysis") or {}
    if not isinstance(analysis, Mapping):
        raise ValueError("analysis must be an object")
    language = str(analysis.get("language", "auto"))
    framework = str(analysis.get("framework", "auto"))

    analysis_started = time.perf_counter_ns()
    graph = FeynMapEngine().analyze(
        str(root),
        language=language,
        framework=framework,
    )
    analysis_ns = time.perf_counter_ns() - analysis_started

    index_started = time.perf_counter_ns()
    index = RegionIndex(graph)
    index_build_ns = time.perf_counter_ns() - index_started

    tasks = _prepared_tasks(graph, spec["tasks"])
    limit = int(spec["region_limit"])
    warmup_rounds = int(spec["warmup_rounds"])
    measurement_rounds = int(spec["measurement_rounds"])

    compact_boundary = prepare_region_routing_index(index)
    conformance_tasks = []
    for task in tasks:
        reference_route = index.route(
            task["query"],
            anchor_node_id=task["anchor_node_id"],
            limit=limit,
        )
        compact_route = route_through_compact_python_boundary(
            index,
            compact_boundary,
            task["query"],
            anchor_node_id=task["anchor_node_id"],
            limit=limit,
        )
        reference_signature = _route_signature(reference_route)
        compact_signature = _route_signature(compact_route)
        if (
            reference_signature["anchor_region"] != compact_signature["anchor_region"]
            or reference_signature["candidate_regions"] != compact_signature["candidate_regions"]
            or reference_signature["selected_regions"] != compact_signature["selected_regions"]
            or set(reference_signature["scores"]) != set(compact_signature["scores"])
        ):
            raise AssertionError(
                "compact routing boundary changed route semantics for %s"
                % task["id"]
            )
        for region_id, score in reference_signature["scores"].items():
            if abs(score - compact_signature["scores"][region_id]) > 1e-12:
                raise AssertionError(
                    "compact routing score mismatch for %s / %s"
                    % (task["id"], region_id)
                )
        conformance_tasks.append(task["id"])

    for _ in range(warmup_rounds):
        for task in tasks:
            index.route(
                task["query"],
                anchor_node_id=task["anchor_node_id"],
                limit=limit,
            )

    signatures = {}
    started = time.perf_counter_ns()
    for _ in range(measurement_rounds):
        for task in tasks:
            route = index.route(
                task["query"],
                anchor_node_id=task["anchor_node_id"],
                limit=limit,
            )
            signatures[task["id"]] = _route_signature(route)
    elapsed_ns = time.perf_counter_ns() - started

    calls = measurement_rounds * len(tasks)
    mean_route_ns = float(elapsed_ns) / float(calls)
    return {
        "schema": BENCHMARK_SCHEMA,
        "name": str(spec.get("name", "S6.4.3 Rust region-routing target")),
        "implementation": "python-reference",
        "project_root": root.name,
        "analysis": {
            "language": language,
            "framework": framework,
            "elapsed_ms": round(float(analysis_ns) / 1_000_000.0, 6),
            "graph_nodes": len(graph.nodes),
            "graph_edges": len(graph.edges),
        },
        "region_index": {
            "region_count": len(index.regions),
            "build_elapsed_ms": round(float(index_build_ns) / 1_000_000.0, 6),
        },
        "boundary_conformance": {
            "schema_version": RUST_ROUTING_BOUNDARY_VERSION,
            "equivalent": True,
            "tasks_checked": conformance_tasks,
        },
        "workload": {
            "task_count": len(tasks),
            "warmup_rounds": warmup_rounds,
            "measurement_rounds": measurement_rounds,
            "route_calls": calls,
            "region_limit": limit,
        },
        "timing": {
            "route_elapsed_ms": round(float(elapsed_ns) / 1_000_000.0, 6),
            "mean_route_us": round(mean_route_ns / 1_000.0, 6),
            "routes_per_second": round(
                (float(calls) * 1_000_000_000.0) / float(elapsed_ns),
                3,
            ) if elapsed_ns else None,
        },
        "signatures": signatures,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the Python reference RegionIndex.route kernel",
    )
    parser.add_argument("spec")
    parser.add_argument("project_root")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    spec_path = Path(args.spec).resolve()
    result = run_benchmark(str(Path(args.project_root)), _load_json(spec_path))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
