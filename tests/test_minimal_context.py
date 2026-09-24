from feynmap.context import estimate_tokens
from feynmap.core import (
    EdgeKind,
    Evidence,
    EvidenceKind,
    NodeKind,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
)
from feynmap.judgment.search import GuidedSearchResult, SearchHit
from feynmap.minimal_context import MinimalContextBudget, MinimalContextPacker


def _evidence():
    return [Evidence(EvidenceKind.STATIC, "fixture", confidence=1.0)]


def _graph_and_result():
    root = SemanticNode("root", "home", NodeKind.FUNCTION, evidence=_evidence())
    helper = SemanticNode("helper", "price_helper", NodeKind.FUNCTION, evidence=_evidence())
    target = SemanticNode("target", "stale_history", NodeKind.CLASS, evidence=_evidence())
    noise = SemanticNode("noise", "unrelated", NodeKind.CLASS, evidence=_evidence())
    edges = [
        SemanticEdge("e1", "root", "helper", EdgeKind.CALLS, 1.0, _evidence()),
        SemanticEdge("e2", "helper", "target", EdgeKind.DEPENDS_ON, 1.0, _evidence()),
        SemanticEdge("e3", "root", "noise", EdgeKind.CONTAINS, 1.0, _evidence()),
    ]
    graph = SemanticGraph([root, helper, target, noise], edges)
    result = GuidedSearchResult(
        mode="node",
        query="find stale price history",
        roots=[root],
        hits=[
            SearchHit(root, depth=0, path_score=0.0),
            SearchHit(helper, depth=1, parent_id="root", via_edge_id="e1", path_score=0.8),
            SearchHit(target, depth=2, parent_id="helper", via_edge_id="e2", path_score=0.9),
            SearchHit(noise, depth=1, parent_id="root", via_edge_id="e3", path_score=0.1),
        ],
        edges=edges,
        trace=[],
        provider=None,
        model=None,
        exhausted=False,
        truncated=True,
    )
    return graph, result


def test_minimal_context_preserves_relationship_endpoints_and_evidence():
    graph, result = _graph_and_result()
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(max_tokens=1400, max_nodes=4, max_edges=3),
    )

    node_ids = set(packed.selected_node_ids)
    for relationship in packed.payload["relationships"]:
        assert relationship["source"] in node_ids
        assert relationship["target"] in node_ids
        assert relationship["evidence"]
    assert all(node["evidence"] for node in packed.payload["nodes"])


def test_minimal_context_keeps_parent_path_for_relevant_deep_hit():
    graph, result = _graph_and_result()
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(max_tokens=1100, max_nodes=3, max_edges=2),
    )

    assert "target" in packed.selected_node_ids
    assert "helper" in packed.selected_node_ids
    assert "root" in packed.selected_node_ids
    assert {"e1", "e2"} <= set(packed.selected_edge_ids)


def test_minimal_context_is_deterministic_and_budgeted():
    graph, result = _graph_and_result()
    packer = MinimalContextPacker(graph)
    budget = MinimalContextBudget(max_tokens=900, max_nodes=3, max_edges=2)

    first = packer.pack(result, budget=budget)
    second = packer.pack(result, budget=budget)

    assert first.to_dict() == second.to_dict()
    assert estimate_tokens(first.payload) == first.delivered_tokens
    assert first.delivered_tokens <= budget.max_tokens
    assert first.delivered_nodes <= budget.max_nodes


def test_minimal_context_can_compress_low_value_noise():
    graph, result = _graph_and_result()
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(max_tokens=900, max_nodes=3, max_edges=2),
    )

    assert packed.delivered_nodes < packed.activated_nodes
    assert packed.token_compression_ratio < 1.0
    assert "noise" not in packed.selected_node_ids


def test_secondary_component_is_marked_as_grounded_anchor():
    graph, result = _graph_and_result()
    remote = SemanticNode("remote", "formatting_markup", NodeKind.FUNCTION, evidence=_evidence())
    graph.add_node(remote)
    result = GuidedSearchResult(
        mode=result.mode,
        query="formatting markup",
        roots=list(result.roots) + [remote],
        hits=list(result.hits) + [SearchHit(remote, depth=0, seed_score=1.0)],
        edges=result.edges,
        trace=result.trace,
        provider=result.provider,
        model=result.model,
        exhausted=result.exhausted,
        truncated=result.truncated,
    )

    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(max_tokens=1200, max_nodes=4, max_edges=2),
    )

    assert "remote" in packed.selected_node_ids
    assert "remote" in packed.payload["anchors"]



def test_minimal_context_protects_all_activation_roots():
    graph, result = _graph_and_result()
    secondary = SemanticNode(
        "secondary-root",
        "stale_model_region",
        NodeKind.CLASS,
        evidence=_evidence(),
    )
    graph.add_node(secondary)
    rooted = GuidedSearchResult(
        mode=result.mode,
        query=result.query,
        roots=list(result.roots) + [secondary],
        hits=list(result.hits) + [
            SearchHit(secondary, depth=0, seed_score=0.7)
        ],
        edges=result.edges,
        trace=result.trace,
        provider=result.provider,
        model=result.model,
        exhausted=result.exhausted,
        truncated=result.truncated,
    )

    packed = MinimalContextPacker(graph).pack(
        rooted,
        budget=MinimalContextBudget(
            max_tokens=1400,
            initial_tokens=700,
            step_tokens=200,
            max_nodes=5,
            max_edges=3,
        ),
    )

    assert "root" in packed.critical_node_ids
    assert "secondary-root" in packed.critical_node_ids
    assert "secondary-root" in packed.selected_node_ids


def test_minimal_context_grows_budget_until_critical_evidence_fits():
    graph, result = _graph_and_result()
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(
            max_tokens=1400,
            initial_tokens=300,
            step_tokens=250,
            max_nodes=4,
            max_edges=3,
        ),
    )

    assert packed.packing_iterations >= 2
    assert packed.selected_budget_tokens > 300
    assert packed.sufficient is True
    assert set(packed.critical_node_ids) <= set(packed.selected_node_ids)


def test_minimal_context_reports_insufficient_when_maximum_is_too_small():
    graph, result = _graph_and_result()
    graph.node("target").name = "stale_history_" + ("expensive" * 120)
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(
            max_tokens=350,
            initial_tokens=300,
            step_tokens=100,
            max_nodes=4,
            max_edges=3,
        ),
    )

    assert packed.sufficient is False
    assert set(packed.critical_node_ids) - set(packed.selected_node_ids)
    assert packed.to_dict()["metrics"]["critical_coverage"] < 1.0
