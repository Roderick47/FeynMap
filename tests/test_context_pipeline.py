from feynmap.context_pipeline import SparseContextPipeline
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.minimal_context import MinimalContextBudget


def _graph():
    root = SemanticNode("root", "home", NodeKind.FUNCTION)
    helper = SemanticNode("helper", "price_helper", NodeKind.FUNCTION)
    target = SemanticNode("target", "stale_history", NodeKind.CLASS)
    noise = SemanticNode("noise", "noise", NodeKind.CLASS)
    return SemanticGraph(
        [root, helper, target, noise],
        [
            SemanticEdge("e1", "root", "helper", EdgeKind.CALLS, 1.0),
            SemanticEdge("e2", "helper", "target", EdgeKind.DEPENDS_ON, 1.0),
            SemanticEdge("e3", "root", "noise", EdgeKind.CONTAINS, 1.0),
        ],
    )


def test_sparse_context_pipeline_runs_activation_then_minimal_delivery():
    pipeline = SparseContextPipeline(_graph())
    result = pipeline.from_node(
        "root",
        "stale history",
        max_depth=2,
        beam_width=2,
        max_nodes=8,
        context_budget=MinimalContextBudget(
            max_tokens=900,
            max_nodes=3,
            max_edges=2,
        ),
    )

    assert result.activation.search.hits
    assert "target" in result.context.selected_node_ids
    assert result.context.delivered_nodes <= result.context.activated_nodes
    assert result.context.delivered_tokens <= 900
    assert result.context.payload["relationships"]


def test_sparse_context_pipeline_serializes_both_stages():
    result = SparseContextPipeline(_graph()).from_node(
        "root",
        "price helper",
        max_depth=1,
        beam_width=2,
        context_budget=MinimalContextBudget(max_tokens=900),
    )

    payload = result.to_dict()
    assert payload["activation"]["stage"] in {"local", "region", "jev"}
    assert payload["context"]["selected_node_ids"]
    assert payload["context"]["metrics"]["delivered_tokens"] > 0
