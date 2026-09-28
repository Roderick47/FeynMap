"""S6.9: same-graph recursive FeynMap workflow comparison with native opt-in.

Analyze the repository once, then compare the complete six-task adaptive +
minimal-context workflow with Python routing vs optional native routing. Native
index construction and any fallback are included in the measured native path.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from unittest.mock import patch

from .activation_benchmark import run_benchmark
from .engine import FeynMapEngine
from .routing import RegionIndex


WORKFLOW_SCHEMA = "feynmap.optional_native_workflow.v1"
WORKFLOW_REGRESSION_LIMIT = 1.15  # Same-run full-workflow median, including native setup.


def _equivalent(reference: Mapping[str, Any], native: Mapping[str, Any]) -> None:
    """Route decisions, activated/packed evidence and recall must not change."""

    if reference["task_count"] != native["task_count"]:
        raise AssertionError("workflow task count changed")
    if reference["summary"]["full_recall_tasks"] != native["summary"]["full_recall_tasks"]:
        raise AssertionError("full-recall task count changed")
    if len(reference["tasks"]) != len(native["tasks"]):
        raise AssertionError("task row count changed")

    exact_keys = (
        "id", "mode", "query", "root",
        "activated_node_ids", "delivered_node_ids",
        "activated_files", "delivered_files",
        "matched_essential_files", "missing_essential_files",
        "matched_essential_symbols", "missing_essential_symbols",
        "essential_full_recall", "essential_recall",
        "activation_essential_recall", "delivered_context_tokens",
        "model_activated_context_tokens", "quality_retention_ratio",
    )
    for original, accelerated in zip(reference["tasks"], native["tasks"]):
        context = original["id"]
        for key in exact_keys:
            if original[key] != accelerated[key]:
                raise AssertionError("%s: evidence/recall changed in %s" % (context, key))
        p_route, n_route = original["region_route"], accelerated["region_route"]
        if (p_route is None) != (n_route is None):
            raise AssertionError("%s: routing stage changed" % context)
        if p_route is not None:
            for field in ("anchor_region", "candidate_regions", "selected_regions"):
                if p_route[field] != n_route[field]:
                    raise AssertionError("%s: region route changed in %s" % (context, field))
            if set(p_route["scores"]) != set(n_route["scores"]):
                raise AssertionError("%s: route score keys changed" % context)
            for key, score in p_route["scores"].items():
                if not math.isclose(
                    float(score), float(n_route["scores"][key]),
                    rel_tol=1e-12, abs_tol=1e-12,
                ):
                    raise AssertionError("%s: route score changed in %s" % (context, key))
        p_adaptive, n_adaptive = original["adaptive"], accelerated["adaptive"]
        if (p_adaptive is None) != (n_adaptive is None):
            raise AssertionError("%s: adaptive decision disappeared" % context)
        if p_adaptive is not None:
            for field in ("stage", "effort", "escalations"):
                if p_adaptive[field] != n_adaptive[field]:
                    raise AssertionError("%s: adaptive decision changed in %s" % (context, field))


def _run_mode(graph, root: Path, dataset, *, native: bool, strategy: str):
    seen = []
    original_init = RegionIndex.__init__

    def tracked_init(instance, *args, **kwargs):
        original_init(instance, *args, **kwargs)
        seen.append(instance)

    # Only the routing-mode environment differs. The analyzed semantic graph,
    # task order, search policy and context policy are identical.
    with patch.object(FeynMapEngine, "analyze", return_value=graph):
        with patch.object(RegionIndex, "__init__", tracked_init):
            with patch.dict(os.environ, {
                "FEYNMAP_NATIVE_ROUTING": "1" if native else "0",
                "FEYNMAP_NATIVE_ROUTING_VERIFY": "0",
            }):
                start = time.perf_counter_ns()
                result = run_benchmark(
                    str(root), dataset,
                    strategy=strategy,
                    context_strategy="minimal",
                )
                elapsed = time.perf_counter_ns() - start

    stats = [instance.native_routing_stats for instance in seen]
    counts = {
        "constructed_region_indexes": len(stats),
        "native_route_calls": sum(item["native_route_calls"] for item in stats),
        "native_setup_attempts": sum(item["setup_attempts"] for item in stats),
        "native_fallbacks": sum(item["fallbacks"] for item in stats),
        "active_native_indexes": sum(item["native_route_calls"] > 0 for item in stats),
    }
    return result, elapsed, counts


def run_workflow(
    root: Path,
    dataset,
    *,
    samples: int = 5,
    strategy: str = "region",
) -> Dict[str, Any]:
    if strategy not in {"region", "adaptive"}:
        raise ValueError("workflow strategy must be region or adaptive")
    if samples < 3 or samples % 2 == 0:
        raise ValueError("samples must be an odd integer >= 3")
    root = root.resolve()
    analysis = dataset.get("analysis") or {}
    start = time.perf_counter_ns()
    graph = FeynMapEngine().analyze(
        str(root),
        language=str(analysis.get("language", "auto")),
        framework=str(analysis.get("framework", "auto")),
    )
    graph_analysis_ns = time.perf_counter_ns() - start

    python_times, native_times = [], []
    python_results, native_results, usage = [], [], []
    order = []
    for sample in range(samples):
        if sample % 2 == 0:
            modes = ("python", "native")
        else:
            modes = ("native", "python")
        order.append("->".join(modes))
        results = {}
        for mode in modes:
            result, duration, counters = _run_mode(
                graph, root, dataset, native=(mode == "native"),
                strategy=strategy,
            )
            results[mode] = result
            if mode == "python":
                python_times.append(duration)
                python_results.append(result)
                if counters["native_route_calls"] or counters["native_setup_attempts"]:
                    raise AssertionError("default Python workflow unexpectedly invoked native")
            else:
                native_times.append(duration)
                native_results.append(result)
                usage.append(counters)
                if counters["native_route_calls"] == 0:
                    if strategy == "region":
                        raise AssertionError("region-first workflow never invoked native routing")
                    if counters["native_setup_attempts"]:
                        raise AssertionError("unneeded adaptive route incurred native setup")
                if counters["native_setup_attempts"] != counters["active_native_indexes"]:
                    raise AssertionError("native index was not prepared exactly once per used index")
                if counters["native_fallbacks"]:
                    raise AssertionError("native path silently fell back during workflow")
        _equivalent(results["python"], results["native"])

    reference = python_results[0]
    for result in python_results[1:]:
        _equivalent(reference, result)
    for result in native_results:
        _equivalent(reference, result)
    python_median = float(statistics.median(python_times))
    native_median = float(statistics.median(native_times))
    ratio = native_median / python_median
    activated = any(item["native_route_calls"] > 0 for item in usage)
    # Adaptive search legitimately stops before region routing on some or all
    # tasks. In that case native setup must remain zero; the path is verified
    # for quality and laziness but its speed ratio is informational only.
    gate = ratio <= WORKFLOW_REGRESSION_LIMIT if activated else True

    return {
        "schema": WORKFLOW_SCHEMA,
        "status": "pass" if gate else "regression",
        "task_count": reference["task_count"],
        "strategy": strategy,
        "context_strategy": "minimal",
        "graph": {
            "nodes": len(graph.nodes), "edges": len(graph.edges),
            "analysis_once_ms": round(graph_analysis_ns / 1e6, 3),
        },
        "measurement": {
            "samples_per_mode": samples,
            "order": order,
            "python_samples_ms": [round(x / 1e6, 3) for x in python_times],
            "native_samples_ms": [round(x / 1e6, 3) for x in native_times],
            "python_median_ms": round(python_median / 1e6, 3),
            "native_median_ms": round(native_median / 1e6, 3),
            "native_to_python_time_ratio": round(ratio, 5),
            "native_workflow_speedup": round(python_median / native_median, 5),
            "regression_limit": WORKFLOW_REGRESSION_LIMIT,
            "regression_gate_applicable": activated,
            "includes_each_native_index_setup": True,
            "excludes_common_graph_analysis": True,
        },
        "quality": {
            "identical_route_selection": True,
            "identical_activated_nodes": True,
            "identical_delivered_nodes": True,
            "identical_delivered_context_tokens": True,
            "identical_essential_recall": True,
            "full_recall_tasks": reference["summary"]["full_recall_tasks"],
            "mean_essential_recall": reference["summary"]["mean_essential_recall"],
        },
        "native_usage": usage,
        "decision": (
            "adaptive local sufficiency avoided region routing and all native setup"
            if not activated
            else "optional native region routing passes full-workflow regression gate"
            if gate
            else "native remains opt-in; full-workflow regression needs investigation"
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="S6.9 recursive optional-native workflow gate")
    parser.add_argument("dataset")
    parser.add_argument("project_root")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--strategy", choices=("region", "adaptive"), default="region")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import _feynmap_native_routing as native
        from .rust_routing_boundary import RUST_ROUTING_BOUNDARY_VERSION
        if native.abi_version() != RUST_ROUTING_BOUNDARY_VERSION:
            raise AssertionError("native ABI mismatch")
        dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        result = run_workflow(
            Path(args.project_root), dataset,
            samples=args.samples, strategy=args.strategy,
        )
    except Exception as exc:
        result = {
            "schema": WORKFLOW_SCHEMA,
            "status": "fail",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            key: result[key]
            for key in ("status", "measurement", "quality", "error", "native_usage")
            if key in result
        },
        sort_keys=True,
    ))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
