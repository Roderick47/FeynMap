import pytest

from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionIndex
from feynmap.rust_routing_boundary import (
    RUST_ROUTING_BOUNDARY_SCHEMA,
    RUST_ROUTING_BOUNDARY_VERSION,
    prepare_region_routing_index,
    prepare_routing_request,
    route_through_compact_python_boundary,
)


def _node(node_id, name, path=None, qualified_name=None):
    return SemanticNode(
        id=node_id,
        name=name,
        kind=NodeKind.FUNCTION,
        qualified_name=qualified_name or name,
        location=SourceLocation(path=path, line=1) if path else None,
    )


def _assert_same_route(reference, compact):
    assert compact.anchor_region == reference.anchor_region
    assert compact.candidate_regions == reference.candidate_regions
    assert compact.selected_regions == reference.selected_regions
    assert set(compact.scores) == set(reference.scores)
    for region_id, score in reference.scores.items():
        assert compact.scores[region_id] == pytest.approx(score, rel=1e-12, abs=1e-12)


def test_compact_boundary_matches_region_index_route():
    root = _node("root", "toggle_price_like", "core/views.py", "core.views.toggle_price_like")
    local = _node("local", "helper", "core/views.py", "core.views.helper")
    signal = _node(
        "signal",
        "refresh_stale_price_on_confirmation",
        "core/signals.py",
        "core.signals.refresh_stale_price_on_confirmation",
    )
    noise = _node("noise", "render_dashboard", "analytics/views.py", "analytics.views.render_dashboard")
    graph = SemanticGraph(
        nodes=[root, local, signal, noise],
        edges=[
            SemanticEdge(
                id="e1",
                source="root",
                target="local",
                kind=EdgeKind.CALLS,
                confidence=1.0,
            )
        ],
    )

    index = RegionIndex(graph)
    prepared = prepare_region_routing_index(index)
    query = "confirm accurate price should refresh stale price"

    reference = index.route(query, anchor_node_id="root", limit=2)
    compact = route_through_compact_python_boundary(
        index,
        prepared,
        query,
        anchor_node_id="root",
        limit=2,
    )

    _assert_same_route(reference, compact)


def test_compact_boundary_preserves_rare_direct_path_slot():
    nodes = [
        _node("root3", "guide_detail", "guides/views.py", "guides.views.guide_detail"),
        _node("broad1", "format_guide_summary", "guides/views.py", "guides.views.format_guide_summary"),
        _node("broad2", "render_guide_list", "guides/list.py", "guides.list.render_guide_list"),
        _node(
            "target3",
            "_formatting_help.html",
            "guides/templates/_formatting_help.html",
            "guides/templates/_formatting_help.html",
        ),
    ]
    index = RegionIndex(SemanticGraph(nodes=nodes))
    prepared = prepare_region_routing_index(index)
    query = "guide formatting headings lists links code quotes"

    reference = index.route(query, anchor_node_id="root3", limit=2)
    compact = route_through_compact_python_boundary(
        index,
        prepared,
        query,
        anchor_node_id="root3",
        limit=2,
    )

    _assert_same_route(reference, compact)
    assert "guides/templates/_formatting_help.html" in compact.selected_regions


def test_compact_boundary_preserves_unknown_query_token_denominator():
    nodes = [
        _node("a", "alpha_handler", "alpha.py", "alpha.alpha_handler"),
        _node("b", "beta_handler", "beta.py", "beta.beta_handler"),
    ]
    index = RegionIndex(SemanticGraph(nodes=nodes))
    prepared = prepare_region_routing_index(index)
    query = "alpha completely_unknown_token"

    request = prepare_routing_request(
        prepared,
        query,
        anchor_region=None,
        limit=2,
    )
    reference = index.route(query, limit=2)
    compact = route_through_compact_python_boundary(
        index,
        prepared,
        query,
        limit=2,
    )

    assert request.unknown_query_term_count >= 1
    _assert_same_route(reference, compact)


def test_compact_boundary_keeps_low_weight_symbol_region_when_it_is_anchor():
    root = _node("symbol-root", "root", None, "pkg.root")
    file_node = _node("file-node", "root_helper", "pkg/helper.py", "pkg.helper.root_helper")
    graph = SemanticGraph(
        nodes=[root, file_node],
        edges=[
            SemanticEdge(
                id="e1",
                source="symbol-root",
                target="file-node",
                kind=EdgeKind.CALLS,
                confidence=1.0,
            )
        ],
    )
    index = RegionIndex(graph)
    prepared = prepare_region_routing_index(index)

    reference = index.route("unmatched tokens", anchor_node_id="symbol-root", limit=2)
    compact = route_through_compact_python_boundary(
        index,
        prepared,
        "unmatched tokens",
        anchor_node_id="symbol-root",
        limit=2,
    )

    _assert_same_route(reference, compact)
    assert compact.anchor_region.startswith("symbol:")


def test_boundary_tables_are_deterministic_and_numeric():
    graph = SemanticGraph(
        nodes=[
            _node("z", "zeta", "z.py", "z.zeta"),
            _node("a", "alpha", "a.py", "a.alpha"),
        ]
    )
    index = RegionIndex(graph)

    first = prepare_region_routing_index(index)
    second = prepare_region_routing_index(index)

    assert first.schema == RUST_ROUTING_BOUNDARY_SCHEMA
    assert first.schema_version == RUST_ROUTING_BOUNDARY_VERSION
    assert first.region_ids == ("a.py", "z.py")
    assert first == second
    assert all(isinstance(value, int) for value in first.kernel.region_term_ids)
    assert all(isinstance(value, int) for value in first.kernel.path_term_ids)
    assert all(isinstance(value, int) for value in first.kernel.adjacency_region_indices)
    assert len(first.kernel.region_term_offsets) == first.kernel.region_count + 1
    assert len(first.kernel.path_term_offsets) == first.kernel.region_count + 1
    assert len(first.kernel.adjacency_offsets) == first.kernel.region_count + 1



def test_native_abi_arguments_are_compact_and_string_free():
    graph = SemanticGraph(
        nodes=[
            _node("a", "alpha", "a.py", "a.alpha"),
            _node("b", "beta", "b.py", "b.beta"),
        ]
    )
    index = RegionIndex(graph)
    prepared = prepare_region_routing_index(index)
    request = prepare_routing_request(
        prepared,
        "alpha unknown_native_term",
        anchor_region=None,
        limit=2,
    )

    constructor_args = prepared.kernel.native_constructor_args()
    route_args = request.native_route_args()

    assert len(constructor_args) == 9
    assert route_args[2] is None
    assert all(
        not isinstance(value, str)
        for collection in (
            prepared.kernel.region_term_ids,
            prepared.kernel.path_term_ids,
            prepared.kernel.adjacency_region_indices,
            request.query_term_ids,
        )
        for value in collection
    )
