from feynmap.activation import ActivationMetrics, measure_guided_search
from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.judgment.search import GuidedSearchResult, SearchHit, SearchStep


def _node(node_id):
    return SemanticNode(
        id=node_id,
        kind=NodeKind.FUNCTION,
        name=node_id,
        qualified_name=node_id,
    )


def test_activation_metrics_report_sparse_search_ratios():
    graph = SemanticGraph()
    nodes = [_node("n%d" % index) for index in range(10)]
    for node in nodes:
        graph.add_node(node)

    result = GuidedSearchResult(
        mode="concept",
        query="authentication",
        roots=[nodes[0]],
        hits=[
            SearchHit(node=nodes[0], depth=0),
            SearchHit(node=nodes[2], depth=1),
            SearchHit(node=nodes[4], depth=2),
        ],
        edges=[],
        trace=[
            SearchStep(
                depth=1,
                frontier=["n0"],
                candidates=["n1", "n2", "n3"],
                selected=["n2"],
            ),
            SearchStep(
                depth=2,
                frontier=["n2"],
                candidates=["n4", "n5"],
                selected=["n4"],
            ),
        ],
        provider=None,
        model=None,
        exhausted=True,
        truncated=True,
    )

    metrics = measure_guided_search(graph, result, delivered_node_ids=["n2", "n4"])

    assert isinstance(metrics, ActivationMetrics)
    assert metrics.total_graph_nodes == 10
    assert metrics.candidate_nodes_seen == 5
    assert metrics.activated_nodes == 3
    assert metrics.delivered_nodes == 2
    assert metrics.candidate_touch_ratio == 0.5
    assert metrics.knowledge_activation_ratio == 0.3
    assert metrics.delivery_to_activation_ratio == 2.0 / 3.0
    assert metrics.search_steps == 2
    assert metrics.exhausted is True
    assert metrics.truncated is True


def test_delivery_is_bounded_to_activated_nodes():
    graph = SemanticGraph()
    nodes = [_node("n0"), _node("n1")]
    for node in nodes:
        graph.add_node(node)

    result = GuidedSearchResult(
        mode="node",
        query="goal",
        roots=[nodes[0]],
        hits=[SearchHit(node=nodes[0], depth=0)],
        edges=[],
        trace=[],
        provider=None,
        model=None,
        exhausted=True,
        truncated=False,
    )

    metrics = measure_guided_search(graph, result, delivered_node_ids=["n0", "n1"])
    assert metrics.delivered_nodes == 1
