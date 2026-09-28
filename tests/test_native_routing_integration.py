"""S6.6 native smoke/equivalence checks.

These are skipped when the optional wheel is absent from ordinary Python CI.
The native-build workflow installs the wheel and must execute them on both
Python 3.8 and Python 3.12.
"""
import json
from pathlib import Path

import pytest

native = pytest.importorskip("_feynmap_native_routing")

from feynmap.engine import FeynMapEngine
from feynmap.query import FeynMapQuery
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionIndex
from feynmap.rust_routing_boundary import (
    RoutingKernelResponse,
    prepare_region_routing_index,
    prepare_routing_request,
    route_compact_python_reference,
)


def _node(identifier, name, path=None):
    return SemanticNode(
        id=identifier,
        name=name,
        kind=NodeKind.FUNCTION,
        qualified_name=name,
        location=SourceLocation(path=path, line=1) if path else None,
    )


def _prepared():
    graph = SemanticGraph(
        nodes=[
            _node("root", "toggle_price_like", "core/views.py"),
            _node("helper", "helper", "core/views.py"),
            _node("signal", "refresh_stale_price_on_confirmation", "core/signals.py"),
            _node("noise", "render_dashboard", "analytics/views.py"),
            _node("symbol", "concept_fallback", None),
        ],
        edges=[
            SemanticEdge(
                id="e1",
                source="root",
                target="helper",
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            SemanticEdge(
                id="e2",
                source="root",
                target="signal",
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
        ],
    )
    index = RegionIndex(graph)
    prepared = prepare_region_routing_index(index)
    return index, prepared


def _compare(native_result, expected, kernel):
    received = RoutingKernelResponse.from_native_result(native_result)
    received.validate(kernel)
    assert received.candidate_regions == expected.candidate_regions
    assert received.selected_region_indices == expected.selected_region_indices
    assert received.selected_scores == pytest.approx(
        expected.selected_scores, rel=1e-12, abs=1e-12
    )


@pytest.mark.parametrize(
    "query,anchor,limit",
    [
        ("confirm accurate price should refresh stale price", "core/views.py", 2),
        ("render dashboard", None, 3),
        ("refresh nonexistent_random_token", "core/views.py", 3),
        ("", None, 2),
        ("", "symbol:concept_fallback", 2),
        ("a completely unknown query word", None, 4),
    ],
)
def test_native_routing_matches_small_compact_reference(query, anchor, limit):
    _, prepared = _prepared()
    rust = native.NativeRegionIndex(*prepared.kernel.native_constructor_args())
    request = prepare_routing_request(prepared, query, anchor_region=anchor, limit=limit)
    reference = route_compact_python_reference(prepared.kernel, request)
    _compare(rust.route(*request.native_route_args()), reference, prepared.kernel)
    assert rust.region_count == len(prepared.region_ids)


def test_native_constructor_rejects_corrupt_csr_instead_of_crashing():
    _, prepared = _prepared()
    args = list(prepared.kernel.native_constructor_args())
    args[3] = (1,) + tuple(args[3][1:])
    with pytest.raises(ValueError, match="offsets must start at zero"):
        native.NativeRegionIndex(*args)

    args = list(prepared.kernel.native_constructor_args())
    args[4] = tuple(args[4]) + (len(prepared.kernel.idf_by_token),)
    args[3] = tuple(args[3][:-1]) + (len(args[4]),)
    with pytest.raises(ValueError, match="out-of-range"):
        native.NativeRegionIndex(*args)


def test_native_route_rejects_invalid_request():
    _, prepared = _prepared()
    rust = native.NativeRegionIndex(*prepared.kernel.native_constructor_args())
    assert prepared.kernel.idf_by_token

    with pytest.raises(ValueError, match="sorted and unique"):
        rust.route((0, 0), 0, None, 2)
    with pytest.raises(ValueError, match="outside vocabulary"):
        rust.route((len(prepared.kernel.idf_by_token),), 0, None, 2)
    with pytest.raises(ValueError, match="anchor region index"):
        rust.route((), 0, len(prepared.region_ids), 2)
    with pytest.raises(ValueError, match="positive"):
        rust.route((), 0, None, 0)


def test_native_index_owns_its_arrays_independently_of_python():
    _, prepared = _prepared()
    arguments = [
        list(value) if isinstance(value, tuple) else value
        for value in prepared.kernel.native_constructor_args()
    ]
    rust = native.NativeRegionIndex(*arguments)
    request = prepare_routing_request(
        prepared,
        "confirm accurate price should refresh stale price",
        anchor_region="core/views.py",
        limit=2,
    )
    before = rust.route(*request.native_route_args())

    arguments[0][0] = 0.0
    arguments[4].clear()
    assert rust.route(*request.native_route_args()) == before



def test_native_routes_feynmap_selfhost_queries():
    """Small recursive smoke; the broader differential corpus belongs to S6.7."""
    root = Path(__file__).resolve().parents[1]
    specification = json.loads(
        (root / "experiments" / "rust_region_routing_s6.json").read_text(
            encoding="utf-8"
        )
    )
    graph = FeynMapEngine().analyze(
        str(root),
        language=specification["analysis"]["language"],
        framework=specification["analysis"]["framework"],
    )
    query_api = FeynMapQuery(graph)
    index = RegionIndex(graph)
    prepared = prepare_region_routing_index(index)
    rust = native.NativeRegionIndex(*prepared.kernel.native_constructor_args())

    for task in specification["tasks"]:
        anchor_node_id = (
            query_api.resolve(task["root"]).id
            if task.get("root")
            else None
        )
        anchor_region = (
            index.region_for_node(anchor_node_id)
            if anchor_node_id is not None
            else None
        )
        request = prepare_routing_request(
            prepared,
            task["query"],
            anchor_region=anchor_region,
            limit=specification["region_limit"],
        )
        expected = route_compact_python_reference(prepared.kernel, request)
        _compare(rust.route(*request.native_route_args()), expected, prepared.kernel)

        original = index.route(
            task["query"],
            anchor_node_id=anchor_node_id,
            limit=specification["region_limit"],
        )
        received = RoutingKernelResponse.from_native_result(
            rust.route(*request.native_route_args())
        )
        assert original.candidate_regions == received.candidate_regions, task["id"]
        selected_ids = tuple(
            prepared.region_ids[value]
            for value in received.selected_region_indices
        )
        assert original.selected_regions == selected_ids, task["id"]
        received_scores = dict(zip(selected_ids, received.selected_scores))
        assert set(original.scores) == set(received_scores), task["id"]
        for region_id, score in original.scores.items():
            assert score == pytest.approx(
                received_scores[region_id], rel=1e-12, abs=1e-12
            ), (task["id"], region_id)
