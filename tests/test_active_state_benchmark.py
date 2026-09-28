from feynmap.active_state_benchmark import run_sequence
from feynmap.active_state import ActiveStateBudget
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.minimal_context import MinimalContextBudget


def _graph():
    nodes = [
        SemanticNode("root", "price_view", NodeKind.FUNCTION, location=SourceLocation("views.py", 1)),
        SemanticNode("helper", "price_helper", NodeKind.FUNCTION, location=SourceLocation("views.py", 5)),
        SemanticNode("history", "stale_history", NodeKind.CLASS, location=SourceLocation("models.py", 1)),
        SemanticNode("audit", "audit_log", NodeKind.CLASS, location=SourceLocation("audit.py", 1)),
    ]
    edges = [
        SemanticEdge("e1", "root", "helper", EdgeKind.CALLS, 1.0),
        SemanticEdge("e2", "helper", "history", EdgeKind.DEPENDS_ON, 1.0),
        SemanticEdge("e3", "history", "audit", EdgeKind.CALLS, 1.0),
    ]
    return SemanticGraph(nodes, edges)


def test_active_state_sequence_measures_reuse_recall_and_growth_avoidance():
    result = run_sequence(
        _graph(),
        "snapshot-test",
        {
            "id": "fixture-loop",
            "steps": [
                {
                    "id": "price",
                    "root": "root",
                    "goal": "price helper",
                    "essential_symbols": ["helper"],
                    "search": {"max_depth": 1, "beam_width": 3},
                },
                {
                    "id": "price-followup",
                    "root": "root",
                    "goal": "price helper",
                    "essential_symbols": ["helper"],
                    "search": {"max_depth": 1, "beam_width": 3},
                },
                {
                    "id": "audit",
                    "root": "root",
                    "goal": "audit log",
                    "essential_symbols": ["audit"],
                    "search": {"max_depth": 3, "beam_width": 4},
                },
            ],
        },
        context_budget=MinimalContextBudget(
            max_tokens=1200,
            max_nodes=4,
            max_edges=4,
            initial_tokens=1200,
        ),
        active_budget=ActiveStateBudget(
            max_nodes=4,
            max_edges=4,
            max_retrievals=4,
        ),
    )

    summary = result["summary"]
    assert result["step_count"] == 3
    assert summary["reuse_steps"] >= 1
    assert summary["reexpanded_steps"] >= 1
    assert summary["mean_active_essential_recall"] == 1.0
    assert summary["full_active_recall_steps"] == 3
    assert summary["cumulative_fresh_context_tokens"] > 0
    assert summary["retained_context_growth_avoided_tokens"] >= 0
    assert summary["final_active_nodes"] <= 4
