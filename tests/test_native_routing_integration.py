"""S6.6 native smoke/equivalence checks.

These are skipped when the optional wheel is absent from ordinary Python CI.
The native-build workflow installs the wheel and must execute them on both
Python 3.8 and Python 3.12.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest

native = pytest.importorskip("_feynmap_native_routing")

from feynmap.engine import FeynMapEngine
from feynmap.query import FeynMapQuery
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionIndex
from feynmap.rust_routing_boundary import (
    RoutingKernelData,
    RoutingKernelRequest,
    MAX_NATIVE_U32,
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



def _numeric_kernel_fixture():
    return RoutingKernelData(
        region_count=2,
        region_weights=(1.0, 1.0),
        idf_by_token=(1.0, 2.0, 3.0),
        unknown_token_idf=4.0,
        region_term_offsets=(0, 2, 3),
        region_term_ids=(0, 1, 2),
        path_term_offsets=(0, 1, 2),
        path_term_ids=(0, 2),
        adjacency_offsets=(0, 1, 2),
        adjacency_region_indices=(1, 0),
    )


@pytest.mark.parametrize(
    "changed,error",
    [
        ({"region_weights": (-1.0, 1.0)}, "finite and non-negative"),
        ({"region_weights": (float("nan"), 1.0)}, "finite and non-negative"),
        ({"idf_by_token": (1.0, 0.0, 3.0)}, "finite and positive"),
        ({"unknown_token_idf": float("inf")}, "finite and positive"),
        ({"region_term_offsets": (1, 2, 3)}, "start at zero"),
        ({"region_term_offsets": (0, 3, 2)}, "monotonic"),
        ({"region_term_offsets": (0, 2, 4)}, "final offset"),
        ({"region_term_ids": (0, 0, 2)}, "sorted and unique"),
        ({"path_term_ids": (3, 2)}, "out-of-range"),
        ({"adjacency_region_indices": (2, 0)}, "out-of-range"),
    ],
)
def test_rust_and_python_reject_same_malformed_csr_contract(changed, error):
    broken = replace(_numeric_kernel_fixture(), **changed)
    with pytest.raises(ValueError):
        broken.validate()
    with pytest.raises(ValueError, match=error):
        native.NativeRegionIndex(*broken.native_constructor_args())


@pytest.mark.parametrize(
    "changed",
    [
        {"query_term_ids": (0, 0)},
        {"query_term_ids": (3,)},
        {"unknown_query_term_count": MAX_NATIVE_U32 + 1},
        {"anchor_region_index": 2},
        {"limit": 0},
        {"limit": MAX_NATIVE_U32 + 1},
    ],
)
def test_rust_and_python_reject_same_invalid_request_domain(changed):
    kernel = _numeric_kernel_fixture()
    rust = native.NativeRegionIndex(*kernel.native_constructor_args())
    request = RoutingKernelRequest((0,), 0, None, 2)
    broken = replace(request, **changed)
    with pytest.raises(ValueError):
        broken.validate(kernel)
    # Python→Rust u32 conversion may raise OverflowError before Rust can
    # return ValueError; both reliably reject the invalid ABI request.
    with pytest.raises((ValueError, OverflowError)):
        rust.route(*broken.native_route_args())


def test_native_empty_index_and_unknown_only_query():
    kernel = RoutingKernelData(
        region_count=0,
        region_weights=(),
        idf_by_token=(),
        unknown_token_idf=1.0,
        region_term_offsets=(0,),
        region_term_ids=(),
        path_term_offsets=(0,),
        path_term_ids=(),
        adjacency_offsets=(0,),
        adjacency_region_indices=(),
    )
    kernel.validate()
    rust = native.NativeRegionIndex(*kernel.native_constructor_args())
    request = RoutingKernelRequest((), 1, None, 3)
    expected = route_compact_python_reference(kernel, request)
    _compare(rust.route(*request.native_route_args()), expected, kernel)
