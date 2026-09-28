"""S6.7 reproducible Python/compact/Rust routing conformance harness.

This is an acceptance test, not a performance benchmark. The oracle fixtures
are independently authored; seeded graphs are deterministic, and the six
recursive FeynMap self-hosting tasks exercise a real repository.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .core import (
    EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation,
)
from .engine import FeynMapEngine
from .query import FeynMapQuery
from .routing import RegionIndex
from .rust_routing_boundary import (
    RUST_ROUTING_BOUNDARY_VERSION, RoutingKernelResponse,
    materialize_region_route, prepare_region_routing_index,
    prepare_routing_request, route_compact_python_reference,
)


CONFORMANCE_SCHEMA = "feynmap.native_routing_conformance.v1"
ORACLE_SCHEMA = "feynmap.native_routing_oracles.v1"
SEED = 677007
SYNTHETIC_SIZES = (1, 37, 513)
SYNTHETIC_REQUESTS_PER_GRAPH = 36
SCORE_ABS_TOL = 1e-12
SCORE_REL_TOL = 1e-12


def _assert_equal_route(left, right, context: str) -> None:
    if left.anchor_region != right.anchor_region:
        raise AssertionError("%s: anchor-region mismatch" % context)
    if left.candidate_regions != right.candidate_regions:
        raise AssertionError("%s: candidate-region count mismatch: %s != %s" % (
            context, left.candidate_regions, right.candidate_regions
        ))
    if left.selected_regions != right.selected_regions:
        raise AssertionError("%s: selected-region mismatch: %s != %s" % (
            context, left.selected_regions, right.selected_regions
        ))
    if set(left.scores) != set(right.scores):
        raise AssertionError("%s: selected-score keys differ" % context)
    for region_id in left.scores:
        a = float(left.scores[region_id])
        b = float(right.scores[region_id])
        if not math.isfinite(a) or not math.isfinite(b) or not math.isclose(
            a, b, rel_tol=SCORE_REL_TOL, abs_tol=SCORE_ABS_TOL
        ):
            raise AssertionError("%s: score mismatch for %s: %r != %r" % (
                context, region_id, a, b
            ))


def _assert_oracle(route, expectation: Mapping[str, Any], context: str) -> None:
    expected_selected = tuple(expectation["selected_regions"])
    if route.selected_regions != expected_selected:
        raise AssertionError("%s: independent expected order %s, got %s" % (
            context, expected_selected, route.selected_regions
        ))
    if route.candidate_regions != int(expectation["candidate_regions"]):
        raise AssertionError("%s: independent candidate count differs" % context)
    expected_scores = expectation["scores"]
    if set(expected_scores) != set(route.scores):
        raise AssertionError("%s: independent score keys differ" % context)
    for key, value in expected_scores.items():
        if not math.isclose(
            float(value), float(route.scores[key]),
            rel_tol=SCORE_REL_TOL, abs_tol=SCORE_ABS_TOL,
        ):
            raise AssertionError("%s: independent score for %s differs" % (
                context, key
            ))


def oracle_graph(case: Mapping[str, Any]) -> SemanticGraph:
    nodes = [
        SemanticNode(
            id=str(node["id"]),
            name=str(node["name"]),
            kind=NodeKind.FUNCTION,
            qualified_name=str(node.get("qualified_name") or node["name"]),
            location=(
                SourceLocation(path=str(node["path"]), line=1)
                if node.get("path") else None
            ),
        )
        for node in case["nodes"]
    ]
    edges = [
        SemanticEdge(
            id=str(edge["id"]),
            source=str(edge["source"]),
            target=str(edge["target"]),
            kind=EdgeKind.CALLS,
            confidence=1.0,
        )
        for edge in case.get("edges", [])
    ]
    return SemanticGraph(nodes=nodes, edges=edges)


def compare_case(
    index: RegionIndex,
    prepared,
    native_index,
    *,
    query: str,
    anchor_node_id: Optional[str] = None,
    limit: int = 8,
    expected: Optional[Mapping[str, Any]] = None,
    context: str,
) -> None:
    """Compare all three paths; native_index=None checks Python/oracle only."""

    anchor_region = (
        index.region_for_node(anchor_node_id)
        if anchor_node_id else None
    )
    request = prepare_routing_request(
        prepared, query, anchor_region=anchor_region, limit=limit
    )
    python_route = index.route(
        query, anchor_node_id=anchor_node_id, limit=limit
    )
    compact_response = route_compact_python_reference(prepared.kernel, request)
    compact_route = materialize_region_route(
        prepared, query, anchor_region=anchor_region, response=compact_response
    )
    _assert_equal_route(python_route, compact_route, context + "/compact")
    if expected is not None:
        _assert_oracle(python_route, expected, context + "/oracle")

    if native_index is not None:
        native_args = request.native_route_args()
        raw_result = native_index.route(*native_args)
        if raw_result != native_index.route(*native_args):
            raise AssertionError(context + ": repeated native route was not deterministic")
        native_response = RoutingKernelResponse.from_native_result(raw_result)
        native_response.validate(prepared.kernel)
        native_route = materialize_region_route(
            prepared, query, anchor_region=anchor_region, response=native_response
        )
        _assert_equal_route(compact_route, native_route, context + "/native-compact")
        _assert_equal_route(python_route, native_route, context + "/native-original")
        if expected is not None:
            _assert_oracle(native_route, expected, context + "/native-oracle")


def _load_oracles(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != ORACLE_SCHEMA or not data.get("cases"):
        raise ValueError("invalid or empty independent routing oracle fixture")
    return data


def run_oracles(
    oracle_path: Path,
    native_module=None,
) -> Tuple[int, List[str]]:
    fixture = _load_oracles(oracle_path)
    count = 0
    identifiers = []
    for case in fixture["cases"]:
        index = RegionIndex(oracle_graph(case))
        prepared = prepare_region_routing_index(index)
        native_index = (
            native_module.NativeRegionIndex(*prepared.kernel.native_constructor_args())
            if native_module is not None else None
        )
        for request in case["requests"]:
            context = "oracle/%s/%s" % (case["id"], request["id"])
            compare_case(
                index, prepared, native_index,
                query=request["query"],
                anchor_node_id=request.get("anchor_node_id"),
                limit=int(request["limit"]),
                expected=request["expected"],
                context=context,
            )
            count += 1
            identifiers.append(context)
    return count, identifiers


def synthetic_graph(count: int, *, seed: int = SEED) -> SemanticGraph:
    """A reproducible, independently generated code-like heterogeneous graph."""

    rng = random.Random(seed + count)
    vocabulary = (
        "route", "context", "snapshot", "search", "budget", "source",
        "evidence", "query", "cost", "state", "activate", "market",
        "render", "graph", "language", "native", "identity", "unicode",
    )
    nodes = []
    for index in range(count):
        first = vocabulary[rng.randrange(len(vocabulary))]
        second = vocabulary[rng.randrange(len(vocabulary))]
        path = (
            None if index % 23 == 0 else
            "package%d/%s%s_%04d.py" % (
                index % 11,
                "test_" if index % 13 == 0 else "",
                first, index,
            )
        )
        nodes.append(
            SemanticNode(
                id="generated-%04d" % index,
                name="%s_%s_handler" % (first, second),
                kind=NodeKind.FUNCTION,
                qualified_name="generated.module%d.fn%d" % (index % 11, index),
                location=SourceLocation(path=path, line=1) if path else None,
                attributes={"category": first, "tags": [second, "verified"]},
            )
        )

    edges = []
    for index in range(count):
        targets = [index + 1]
        if index % 5 == 0:
            targets.append(index + 7)
        for target in targets:
            if target < count:
                edges.append(
                    SemanticEdge(
                        id="generated-edge-%d-%d" % (index, target),
                        source=nodes[index].id,
                        target=nodes[target].id,
                        kind=EdgeKind.CALLS,
                        confidence=1.0,
                    )
                )
    return SemanticGraph(nodes=nodes, edges=edges)


def run_seeded(native_module, *, sizes: Sequence[int] = SYNTHETIC_SIZES) -> Tuple[int, List[int]]:
    rng = random.Random(SEED)
    token_pool = (
        "route", "context", "snapshot", "search", "budget", "source",
        "evidence", "query", "state", "render", "graph", "native",
        "absent_untouched", "Straße", "THE", "and",
    )
    count = 0
    region_counts = []
    for size in sizes:
        graph = synthetic_graph(size)
        index = RegionIndex(graph)
        prepared = prepare_region_routing_index(index)
        native_index = (
            native_module.NativeRegionIndex(*prepared.kernel.native_constructor_args())
            if native_module is not None else None
        )
        region_counts.append(len(index.regions))
        for request_index in range(SYNTHETIC_REQUESTS_PER_GRAPH):
            if request_index % 12 == 0:
                query = ""
            elif request_index % 12 == 1:
                query = "the and to"
            elif request_index % 12 == 2:
                query = "unknown_token_%d" % request_index
            else:
                query = " ".join(
                    rng.choice(token_pool)
                    for _ in range(1 + (request_index % 5))
                )
            anchor_node_id = (
                graph.nodes[rng.randrange(size)].id
                if request_index % 3 and size else None
            )
            limit = (1, 2, 4, 8, 16, 64)[request_index % 6]
            compare_case(
                index, prepared, native_index,
                query=query,
                anchor_node_id=anchor_node_id,
                limit=limit,
                context="seeded/%d/%d" % (size, request_index),
            )
            count += 1
    return count, region_counts


def run_selfhost(repo_root: Path, spec_path: Path, native_module) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    analysis = spec.get("analysis", {})
    graph = FeynMapEngine().analyze(
        str(repo_root),
        language=analysis.get("language", "auto"),
        framework=analysis.get("framework", "auto"),
    )
    resolver = FeynMapQuery(graph)
    index = RegionIndex(graph)
    prepared = prepare_region_routing_index(index)
    native_index = native_module.NativeRegionIndex(
        *prepared.kernel.native_constructor_args()
    )
    count = 0
    for task in spec["tasks"]:
        anchor_node_id = (
            resolver.resolve(task["root"]).id
            if task.get("root") else None
        )
        compare_case(
            index, prepared, native_index,
            query=task["query"],
            anchor_node_id=anchor_node_id,
            limit=int(spec["region_limit"]),
            context="selfhost/%s" % task["id"],
        )
        count += 1
    return count


def run_conformance(repo_root: Path, native_module) -> Dict[str, Any]:
    oracle_count, oracle_ids = run_oracles(
        repo_root / "tests/fixtures/contracts/s6_7_routing_oracles.json",
        native_module,
    )
    seeded_count, region_counts = run_seeded(native_module)
    selfhost_count = run_selfhost(
        repo_root,
        repo_root / "experiments/rust_region_routing_s6.json",
        native_module,
    )
    return {
        "schema": CONFORMANCE_SCHEMA,
        "native_abi_version": native_module.abi_version(),
        "python_boundary_version": RUST_ROUTING_BOUNDARY_VERSION,
        "status": "pass",
        "independent_oracles": oracle_count,
        "independent_oracle_ids": oracle_ids,
        "seed": SEED,
        "synthetic_graph_nodes": list(SYNTHETIC_SIZES),
        "synthetic_region_counts": region_counts,
        "seeded_requests": seeded_count,
        "recursive_selfhost_requests": selfhost_count,
        "total_cases": oracle_count + seeded_count + selfhost_count,
        "comparison": "original Python vs compact Python vs compiled Rust",
        "selected_order_exact": True,
        "score_abs_tol": SCORE_ABS_TOL,
        "score_rel_tol": SCORE_REL_TOL,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run native routing differential conformance acceptance corpus"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    import _feynmap_native_routing as native

    result = run_conformance(root, native)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "total_cases": result["total_cases"],
        "independent_oracles": result["independent_oracles"],
        "seeded_requests": result["seeded_requests"],
        "recursive_selfhost_requests": result["recursive_selfhost_requests"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
