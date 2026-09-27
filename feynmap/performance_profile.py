"""Reproducible Python hot-path profiling for the sparse substrate.

Profiles are diagnostic measurements. They identify where Python spends time;
they are not latency claims and do not apply any optimization.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .activation_benchmark import run_benchmark as run_activation_benchmark
from .tool_routing_benchmark import run_benchmark as run_tool_routing_benchmark


PROFILE_SCHEMA = "feynmap.performance_profile.v1"


def _load_json(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("profile workload datasets must contain JSON objects")
    return payload


def _function_name(key: Tuple[str, int, str], source_root: Path) -> str:
    filename, line, name = key
    if filename.startswith("~"):
        return "%s:%s" % (filename, name)
    try:
        relative = Path(filename).resolve().relative_to(source_root)
        display = str(relative).replace("\\", "/")
    except (OSError, ValueError):
        display = os.path.basename(filename)
    return "%s:%d(%s)" % (display, line, name)


def _is_feynmap_function(key: Tuple[str, int, str], source_root: Path) -> bool:
    try:
        relative = Path(key[0]).resolve().relative_to(source_root)
    except (OSError, ValueError):
        return False
    return relative.parts[:1] == ("feynmap",)


def _rows(
    stats: Mapping[Tuple[str, int, str], Tuple[Any, ...]],
    source_root: Path,
    *,
    metric_index: int,
    limit: int,
    only_feynmap: bool = False,
) -> List[Dict[str, Any]]:
    items = [
        (key, value)
        for key, value in stats.items()
        if not only_feynmap or _is_feynmap_function(key, source_root)
    ]
    items.sort(
        key=lambda item: (-float(item[1][metric_index]), _function_name(item[0], source_root))
    )
    return [
        {
            "function": _function_name(key, source_root),
            "primitive_calls": int(value[0]),
            "total_calls": int(value[1]),
            "internal_seconds": round(float(value[2]), 9),
            "cumulative_seconds": round(float(value[3]), 9),
        }
        for key, value in items[:limit]
    ]


def _module_internal_time(
    stats: Mapping[Tuple[str, int, str], Tuple[Any, ...]],
    source_root: Path,
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    totals: Dict[str, float] = {}
    for key, value in stats.items():
        if not _is_feynmap_function(key, source_root):
            continue
        relative = str(Path(key[0]).resolve().relative_to(source_root)).replace("\\", "/")
        totals[relative] = totals.get(relative, 0.0) + float(value[2])
    return [
        {"module": module, "internal_seconds": round(seconds, 9)}
        for module, seconds in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def profile_callable(
    name: str,
    action: Callable[[], Any],
    *,
    source_root: Path,
    top_n: int = 20,
) -> Tuple[Dict[str, Any], Any]:
    """Run one action under cProfile and return portable aggregate statistics."""
    if not isinstance(name, str) or not name:
        raise ValueError("profile name is required")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise ValueError("top_n must be a positive integer")

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    try:
        result = action()
    finally:
        profiler.disable()
    elapsed_seconds = time.perf_counter() - started
    report = pstats.Stats(profiler)
    stats = report.stats
    return {
        "name": name,
        "elapsed_ms": round(elapsed_seconds * 1000.0, 6),
        "total_calls": int(report.total_calls),
        "primitive_calls": int(report.prim_calls),
        "top_cumulative_functions": _rows(
            stats, source_root, metric_index=3, limit=top_n,
        ),
        "top_internal_functions": _rows(
            stats, source_root, metric_index=2, limit=top_n,
        ),
        "top_feynmap_internal_functions": _rows(
            stats, source_root, metric_index=2, limit=top_n, only_feynmap=True,
        ),
        "top_feynmap_modules_by_internal_time": _module_internal_time(
            stats, source_root, limit=top_n,
        ),
    }, result


def validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != PROFILE_SCHEMA:
        raise ValueError("unsupported performance-profile schema")
    workloads = spec.get("workloads")
    if not isinstance(workloads, list) or not workloads:
        raise ValueError("performance profile requires a non-empty workloads list")
    names = []
    for workload in workloads:
        if not isinstance(workload, Mapping):
            raise ValueError("each profile workload must be an object")
        name = workload.get("name")
        kind = workload.get("kind")
        dataset = workload.get("dataset")
        iterations = workload.get("iterations", 1)
        if not isinstance(name, str) or not name:
            raise ValueError("each profile workload requires a non-empty name")
        if kind not in {"activation", "tool_routing"}:
            raise ValueError("profile workload kind must be activation or tool_routing")
        if not isinstance(dataset, str) or not dataset:
            raise ValueError("each profile workload requires a dataset path")
        if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
            raise ValueError("profile workload iterations must be a positive integer")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("profile workload names must be unique")
    top_n = spec.get("top_n", 20)
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise ValueError("profile top_n must be a positive integer")


def _workload_action(
    workload: Mapping[str, Any],
    *,
    project_root: Path,
    spec_directory: Path,
) -> Callable[[], Any]:
    dataset = _load_json(spec_directory / str(workload["dataset"]))
    iterations = int(workload["iterations"])
    kind = str(workload["kind"])

    if kind == "activation":
        strategy = str(workload.get("strategy", "adaptive"))
        context_strategy = str(workload.get("context_strategy", "minimal"))

        def action():
            result = None
            for _ in range(iterations):
                result = run_activation_benchmark(
                    str(project_root),
                    dataset,
                    strategy=strategy,
                    context_strategy=context_strategy,
                )
            return result

        return action

    def action():
        result = None
        for _ in range(iterations):
            result = run_tool_routing_benchmark(dataset)
        return result

    return action


def _result_summary(kind: str, result: Mapping[str, Any]) -> Dict[str, Any]:
    if kind == "activation":
        return {
            "task_count": result.get("task_count"),
            "graph_nodes": (result.get("analysis") or {}).get("graph_nodes"),
            "graph_edges": (result.get("analysis") or {}).get("graph_edges"),
            "mean_routing_elapsed_ms": (result.get("summary") or {}).get("mean_routing_elapsed_ms"),
        }
    return {
        "task_count": result.get("task_count"),
        "tool_count": result.get("tool_count"),
        "top1_accuracy": (result.get("summary") or {}).get("top1_accuracy"),
        "schema_token_reduction_ratio": (result.get("summary") or {}).get("schema_token_reduction_ratio"),
    }


def run_profile(
    spec: Mapping[str, Any],
    project_root: Path,
    *,
    spec_directory: Optional[Path] = None,
) -> Dict[str, Any]:
    validate_spec(spec)
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError("profile project root must be a directory")
    directory = Path(spec_directory or ".").resolve()
    top_n = int(spec.get("top_n", 20))
    reports = []
    for workload in spec["workloads"]:
        action = _workload_action(
            workload,
            project_root=root,
            spec_directory=directory,
        )
        report, result = profile_callable(
            str(workload["name"]), action, source_root=root, top_n=top_n,
        )
        report["kind"] = str(workload["kind"])
        report["iterations"] = int(workload["iterations"])
        report["workload_summary"] = _result_summary(str(workload["kind"]), result)
        reports.append(report)
    return {
        "schema": PROFILE_SCHEMA,
        "name": str(spec.get("name", "FeynMap performance profile")),
        "project_root": root.name,
        "top_n": top_n,
        "workloads": reports,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Profile FeynMap sparse-substrate Python hot paths.",
    )
    parser.add_argument("spec", help="Path to a feynmap.performance_profile.v1 JSON spec")
    parser.add_argument("project_root", help="Repository root to profile")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    spec_path = Path(args.spec).resolve()
    spec = _load_json(spec_path)
    result = run_profile(spec, Path(args.project_root), spec_directory=spec_path.parent)
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
