"""S6.8 paired performance acceptance for the optional Rust region router.

Measures the real Python -> native -> Python route path on the same analyzed
self-hosted graph as the original Python route baseline. Static native index
preparation/construction is measured separately and charged through a
break-even calculation. Normal production routing is not modified.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .engine import FeynMapEngine
from .query import FeynMapQuery
from .routing import RegionIndex
from .rust_routing_boundary import (
    RUST_ROUTING_BOUNDARY_VERSION,
    RoutingKernelResponse,
    materialize_region_route,
    prepare_region_routing_index,
    prepare_routing_request,
)
from .rust_routing_conformance import _assert_equal_route
from .rust_routing_benchmark import BENCHMARK_SCHEMA, validate_spec


PERFORMANCE_SCHEMA = "feynmap.native_routing_performance.v1"
PERFORMANCE_THRESHOLD = 2.0
SAMPLE_ROUNDS = 5


def evaluate_acceptance(
    python_samples_ns: Sequence[int],
    native_samples_ns: Sequence[int],
    *,
    route_calls_per_sample: int,
    extra_native_setup_ns: int,
    minimum_speedup: float = PERFORMANCE_THRESHOLD,
) -> Dict[str, Any]:
    """Return a deterministic, testable performance decision from raw samples."""

    if not python_samples_ns or len(python_samples_ns) != len(native_samples_ns):
        raise ValueError("paired non-empty Python/native samples are required")
    if any(value <= 0 for value in tuple(python_samples_ns) + tuple(native_samples_ns)):
        raise ValueError("timings must be positive")
    if route_calls_per_sample <= 0 or extra_native_setup_ns < 0:
        raise ValueError("route calls must be positive and setup non-negative")
    if minimum_speedup <= 1.0 or not math.isfinite(minimum_speedup):
        raise ValueError("minimum speedup must exceed 1")

    baseline_ns = float(statistics.median(python_samples_ns))
    native_ns = float(statistics.median(native_samples_ns))
    python_ns_per_call = baseline_ns / route_calls_per_sample
    native_ns_per_call = native_ns / route_calls_per_sample
    saved_ns_per_call = python_ns_per_call - native_ns_per_call
    ratio = baseline_ns / native_ns
    break_even = (
        int(math.ceil(float(extra_native_setup_ns) / saved_ns_per_call))
        if saved_ns_per_call > 0 else None
    )
    route_gate = ratio >= minimum_speedup
    return {
        "python_median_elapsed_ms": round(baseline_ns / 1e6, 6),
        "native_median_elapsed_ms": round(native_ns / 1e6, 6),
        "python_mean_route_us": round(python_ns_per_call / 1e3, 6),
        "native_mean_route_us": round(native_ns_per_call / 1e3, 6),
        "python_routes_per_second": round(1e9 / python_ns_per_call, 3),
        "native_routes_per_second": round(1e9 / native_ns_per_call, 3),
        "end_to_end_route_speedup": round(ratio, 6),
        "net_saved_us_per_reused_call": round(saved_ns_per_call / 1e3, 6),
        "minimum_speedup": minimum_speedup,
        "route_speed_gate_pass": route_gate,
        "extra_setup_ms": round(extra_native_setup_ns / 1e6, 6),
        "break_even_route_calls": break_even,
        "first_route_with_setup_faster": (
            extra_native_setup_ns + native_ns_per_call < python_ns_per_call
        ),
        "status": "pass" if route_gate else "fail",
    }


def _compare_quality(reference, native_route, context: str) -> None:
    _assert_equal_route(reference, native_route, context)


def _run_python(index: RegionIndex, tasks, limit: int, rounds: int) -> int:
    last = None
    start = time.perf_counter_ns()
    for _ in range(rounds):
        for task in tasks:
            last = index.route(
                task["query"],
                anchor_node_id=task["anchor_node_id"],
                limit=limit,
            )
    elapsed = time.perf_counter_ns() - start
    if last is None:
        raise AssertionError("empty benchmark")
    return elapsed


def _run_native(index, prepared, native_index, tasks, limit: int, rounds: int) -> int:
    last = None
    start = time.perf_counter_ns()
    for _ in range(rounds):
        for task in tasks:
            anchor_region = (
                index.region_for_node(task["anchor_node_id"])
                if task["anchor_node_id"] else None
            )
            request = prepare_routing_request(
                prepared,
                task["query"],
                anchor_region=anchor_region,
                limit=limit,
            )
            raw = native_index.route(*request.native_route_args())
            result = RoutingKernelResponse.from_native_result(raw)
            last = materialize_region_route(
                prepared,
                task["query"],
                anchor_region=anchor_region,
                response=result,
            )
    elapsed = time.perf_counter_ns() - start
    if last is None:
        raise AssertionError("empty benchmark")
    return elapsed


def _run_native_kernel_only(native_index, precomputed_requests, rounds: int) -> int:
    """Diagnostic only: PyO3/native route with query preparation excluded."""

    last = None
    start = time.perf_counter_ns()
    for _ in range(rounds):
        for request in precomputed_requests:
            last = native_index.route(*request.native_route_args())
    elapsed = time.perf_counter_ns() - start
    if last is None:
        raise AssertionError("empty benchmark")
    return elapsed


def run_performance(
    project_root: str,
    spec: Mapping[str, Any],
    native_module,
    *,
    samples: int = SAMPLE_ROUNDS,
) -> Dict[str, Any]:
    validate_spec(spec)
    if samples < 3 or samples % 2 == 0:
        raise ValueError("samples must be an odd count of at least three")
    if native_module.abi_version() != RUST_ROUTING_BOUNDARY_VERSION:
        raise AssertionError("native routing ABI mismatch")

    root = Path(project_root).resolve()
    analysis = spec.get("analysis") or {}
    if not isinstance(analysis, Mapping):
        raise ValueError("analysis must be an object")
    start = time.perf_counter_ns()
    graph = FeynMapEngine().analyze(
        str(root),
        language=str(analysis.get("language", "auto")),
        framework=str(analysis.get("framework", "auto")),
    )
    analysis_ns = time.perf_counter_ns() - start

    start = time.perf_counter_ns()
    index = RegionIndex(graph)
    python_index_build_ns = time.perf_counter_ns() - start

    query = FeynMapQuery(graph)
    tasks = []
    for task in spec["tasks"]:
        anchor_node_id = (
            query.resolve(str(task["root"])).id
            if task.get("root") else None
        )
        tasks.append({
            "id": str(task["id"]),
            "query": str(task["query"]),
            "anchor_node_id": anchor_node_id,
        })

    start = time.perf_counter_ns()
    prepared = prepare_region_routing_index(index)
    native_preparation_ns = time.perf_counter_ns() - start
    start = time.perf_counter_ns()
    native_index = native_module.NativeRegionIndex(
        *prepared.kernel.native_constructor_args()
    )
    native_construction_ns = time.perf_counter_ns() - start
    extra_setup_ns = native_preparation_ns + native_construction_ns

    limit = int(spec["region_limit"])
    precomputed_requests = []
    # Correctness checks and request precomputation remain OUTSIDE timed loops.
    for task in tasks:
        anchor_region = (
            index.region_for_node(task["anchor_node_id"])
            if task["anchor_node_id"] else None
        )
        request = prepare_routing_request(
            prepared, task["query"], anchor_region=anchor_region, limit=limit,
        )
        precomputed_requests.append(request)
        reference = index.route(
            task["query"], anchor_node_id=task["anchor_node_id"], limit=limit,
        )
        native_response = RoutingKernelResponse.from_native_result(
            native_index.route(*request.native_route_args())
        )
        native_route = materialize_region_route(
            prepared,
            task["query"],
            anchor_region=anchor_region,
            response=native_response,
        )
        _compare_quality(reference, native_route, task["id"])

    warmup_rounds = int(spec["warmup_rounds"])
    measurement_rounds = int(spec["measurement_rounds"])
    _run_python(index, tasks, limit, warmup_rounds)
    _run_native(index, prepared, native_index, tasks, limit, warmup_rounds)
    _run_native_kernel_only(native_index, precomputed_requests, warmup_rounds)

    # Alternate order to reduce systematic first/second-run bias. The Python
    # and Rust route calls happen on the SAME runner and same graph.
    python_samples_ns = []
    native_samples_ns = []
    order = []
    for sample in range(samples):
        if sample % 2 == 0:
            order.append("python-then-native")
            python_samples_ns.append(
                _run_python(index, tasks, limit, measurement_rounds)
            )
            native_samples_ns.append(
                _run_native(index, prepared, native_index, tasks, limit, measurement_rounds)
            )
        else:
            order.append("native-then-python")
            native_samples_ns.append(
                _run_native(index, prepared, native_index, tasks, limit, measurement_rounds)
            )
            python_samples_ns.append(
                _run_python(index, tasks, limit, measurement_rounds)
            )

    native_kernel_samples_ns = [
        _run_native_kernel_only(native_index, precomputed_requests, measurement_rounds)
        for _ in range(samples)
    ]
    route_calls = measurement_rounds * len(tasks)
    decision = evaluate_acceptance(
        python_samples_ns,
        native_samples_ns,
        route_calls_per_sample=route_calls,
        extra_native_setup_ns=extra_setup_ns,
    )
    native_kernel_median_ns = float(statistics.median(native_kernel_samples_ns))
    return {
        "schema": PERFORMANCE_SCHEMA,
        "implementation": "optional-native-shadow-benchmark",
        "native_abi_version": native_module.abi_version(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "architecture": platform.machine(),
        },
        "graph": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "regions": len(index.regions),
            "analysis_elapsed_ms": round(analysis_ns / 1e6, 6),
            "python_index_build_ms": round(python_index_build_ns / 1e6, 6),
        },
        "native_setup": {
            "numeric_preparation_ms": round(native_preparation_ns / 1e6, 6),
            "native_owned_index_construction_ms": round(native_construction_ns / 1e6, 6),
            "extra_native_setup_ms": round(extra_setup_ns / 1e6, 6),
        },
        "workload": {
            "task_ids": [item["id"] for item in tasks],
            "route_calls_per_sample": route_calls,
            "warmup_rounds": warmup_rounds,
            "measurement_rounds": measurement_rounds,
            "paired_samples": samples,
            "order": order,
            "quality_equivalence": True,
        },
        "raw_samples_ms": {
            "original_python": [round(value / 1e6, 6) for value in python_samples_ns],
            "native_end_to_end": [round(value / 1e6, 6) for value in native_samples_ns],
            "native_kernel_only": [round(value / 1e6, 6) for value in native_kernel_samples_ns],
        },
        "kernel_diagnostic": {
            "native_kernel_including_ffi_mean_route_us": round(
                native_kernel_median_ns / route_calls / 1e3, 6
            ),
            "excluded_from_acceptance": True,
        },
        "decision": decision,
        "production_router_unchanged": True,
        "caveats": [
            "The same-run repeated-route decision excludes graph analysis and the common Python RegionIndex build.",
            "The break-even count charges extra native preparation and construction once.",
            "This benchmark does not claim full adaptive/minimal-context workflow speedup.",
            "Only the full native end-to-end path, not isolated Rust execution, controls acceptance.",
        ],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="S6.8 paired Rust routing performance gate")
    parser.add_argument("spec")
    parser.add_argument("project_root")
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=SAMPLE_ROUNDS)
    args = parser.parse_args(argv)
    import _feynmap_native_routing as native

    with Path(args.spec).open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    result = run_performance(args.project_root, spec, native, samples=args.samples)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "python": result["environment"]["python"],
        "quality_equivalence": result["workload"]["quality_equivalence"],
        "speedup": result["decision"]["end_to_end_route_speedup"],
        "break_even_calls": result["decision"]["break_even_route_calls"],
        "gate": result["decision"]["status"],
    }, sort_keys=True))
    return 0 if result["decision"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
