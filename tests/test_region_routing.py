from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionFirstSearch, RegionIndex


def _node(node_id, name, path, qualified_name=None):
    return SemanticNode(
        id=node_id,
        name=name,
        kind=NodeKind.FUNCTION,
        qualified_name=qualified_name or name,
        location=SourceLocation(path=path, line=1),
    )


def test_region_index_routes_globally_relevant_file_even_without_graph_edge():
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
        edges=[SemanticEdge(id="e1", source="root", target="local", kind=EdgeKind.CALLS, confidence=1.0)],
    )

    index = RegionIndex(graph)
    route = index.route(
        "confirm accurate price should refresh stale price",
        anchor_node_id="root",
        limit=2,
    )

    assert "core/views.py" in route.selected_regions
    assert "core/signals.py" in route.selected_regions


def test_region_first_search_activates_seed_from_disconnected_relevant_region():
    root = _node("root", "toggle_price_like", "core/views.py", "core.views.toggle_price_like")
    local = _node("local", "helper", "core/views.py", "core.views.helper")
    signal = _node(
        "signal",
        "refresh_stale_price_on_confirmation",
        "core/signals.py",
        "core.signals.refresh_stale_price_on_confirmation",
    )
    graph = SemanticGraph(
        nodes=[root, local, signal],
        edges=[SemanticEdge(id="e1", source="root", target="local", kind=EdgeKind.CALLS, confidence=1.0)],
    )

    result = RegionFirstSearch(graph, region_limit=2, seed_limit=4).from_node(
        "root",
        "confirm accurate price should refresh stale price",
        max_depth=1,
        beam_width=2,
        max_nodes=8,
    )

    activated = {hit.node.id for hit in result.search.hits}
    assert "root" in activated
    assert "signal" in activated
    assert result.route.region_touch_ratio <= 1.0
