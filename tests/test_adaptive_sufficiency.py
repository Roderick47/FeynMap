from feynmap.adaptive import AdaptiveSparseSearch
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionIndex
from feynmap.sufficiency import SufficiencyEvaluator


def _node(node_id, name, path, kind=NodeKind.FUNCTION):
    return SemanticNode(
        id=node_id,
        name=name,
        kind=kind,
        qualified_name=name,
        location=SourceLocation(path=path, line=1),
    )


def test_sufficiency_stops_when_regions_add_no_new_query_information():
    root = _node("root", "price_accuracy", "core/views.py")
    helper = _node("helper", "accurate_price", "core/models.py")
    graph = SemanticGraph(
        nodes=[root, helper],
        edges=[
            SemanticEdge(
                id="edge",
                source="root",
                target="helper",
                kind=EdgeKind.CALLS,
                confidence=1.0,
            )
        ],
    )

    result = AdaptiveSparseSearch(graph, region_limit=2).from_node(
        "root",
        "accurate price",
        max_depth=1,
        beam_width=2,
        max_nodes=8,
    )

    assert result.stage == "local"
    assert result.escalations == ()
    assert result.local_sufficiency.sufficient is True


def test_sufficiency_escalates_when_unopened_region_contains_missing_query_term():
    root = _node("root", "price_view", "core/views.py")
    local = _node("local", "price_helper", "core/views.py")
    stale = _node("stale", "stale_history", "core/models.py")
    graph = SemanticGraph(
        nodes=[root, local, stale],
        edges=[
            SemanticEdge(
                id="edge",
                source="root",
                target="local",
                kind=EdgeKind.CALLS,
                confidence=1.0,
            )
        ],
    )

    evaluator = SufficiencyEvaluator(
        graph,
        region_index=RegionIndex(graph),
        specific_term_threshold=0.60,
    )
    result = AdaptiveSparseSearch(
        graph,
        region_limit=2,
        sufficiency=evaluator,
    ).from_node(
        "root",
        "price stale history",
        max_depth=1,
        beam_width=2,
        max_nodes=8,
    )

    assert result.stage == "region"
    assert result.escalations == ("region",)
    assert result.local_sufficiency.sufficient is False
    assert result.local_sufficiency.novel_region_gain > 0
    assert "stale" in {hit.node.id for hit in result.search.hits}


def test_sufficiency_result_is_deterministic_for_same_graph_and_query():
    root = _node("root", "home", "views.py")
    template = _node("template", "home_template", "templates/home.html", NodeKind.UI_SURFACE)
    graph = SemanticGraph(
        nodes=[root, template],
        edges=[
            SemanticEdge(
                id="render",
                source="root",
                target="template",
                kind=EdgeKind.RENDERS,
                confidence=1.0,
            )
        ],
    )
    index = RegionIndex(graph)
    evaluator = SufficiencyEvaluator(graph, region_index=index)
    route = index.route("home template", anchor_node_id="root", limit=2)

    first = AdaptiveSparseSearch(graph, region_limit=2).from_node(
        "root",
        "home template",
        max_depth=1,
        beam_width=2,
    )
    second = AdaptiveSparseSearch(graph, region_limit=2).from_node(
        "root",
        "home template",
        max_depth=1,
        beam_width=2,
    )

    assert first.local_sufficiency.to_dict() == second.local_sufficiency.to_dict()
    assert route.selected_regions == first.route.selected_regions
