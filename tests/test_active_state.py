import pytest

from feynmap.active_state import (
    ACTIVE_STATE_SCHEMA,
    ActiveState,
    ActiveStateBudget,
    ActiveStateInvalidated,
    ActiveStateRuntime,
)
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.minimal_context import MinimalContextBudget


def _graph():
    root = SemanticNode(
        "root",
        "home",
        NodeKind.FUNCTION,
        location=SourceLocation("views.py", 1),
    )
    helper = SemanticNode(
        "helper",
        "price_helper",
        NodeKind.FUNCTION,
        location=SourceLocation("views.py", 10),
    )
    history = SemanticNode(
        "history",
        "stale_history",
        NodeKind.CLASS,
        location=SourceLocation("models.py", 5),
    )
    audit = SemanticNode(
        "audit",
        "audit_log",
        NodeKind.CLASS,
        location=SourceLocation("audit.py", 3),
    )
    noise = SemanticNode(
        "noise",
        "unrelated_noise",
        NodeKind.CLASS,
        location=SourceLocation("noise.py", 1),
    )
    return SemanticGraph(
        [root, helper, history, audit, noise],
        [
            SemanticEdge("e1", "root", "helper", EdgeKind.CALLS, 1.0),
            SemanticEdge("e2", "helper", "history", EdgeKind.DEPENDS_ON, 1.0),
            SemanticEdge("e3", "history", "audit", EdgeKind.CALLS, 1.0),
            SemanticEdge("e4", "root", "noise", EdgeKind.CONTAINS, 1.0),
        ],
    )


def _context_budget():
    return MinimalContextBudget(
        max_tokens=900,
        max_nodes=4,
        max_edges=4,
        initial_tokens=900,
    )


def test_active_state_serializes_references_instead_of_graph_copies():
    runtime = ActiveStateRuntime(_graph(), "snapshot-a")
    transition = runtime.begin_from_node(
        "root",
        "price helper",
        context_budget=_context_budget(),
        max_depth=1,
        beam_width=3,
    )

    payload = transition.state.to_dict()

    assert payload["schema"] == ACTIVE_STATE_SCHEMA
    assert payload["snapshot_id"] == "snapshot-a"
    assert payload["active_node_ids"]
    assert "nodes" not in payload
    assert "relationships" not in payload
    assert all(isinstance(item, str) for item in payload["active_node_ids"])


def test_active_state_rehydrates_exact_canonical_graph_evidence():
    graph = _graph()
    runtime = ActiveStateRuntime(graph, "snapshot-a")
    state = runtime.begin_from_node(
        "root",
        "price helper",
        context_budget=_context_budget(),
        max_depth=1,
        beam_width=3,
    ).state

    hydrated = runtime.rehydrate(state)
    hydrated_by_id = {item["id"]: item for item in hydrated["nodes"]}

    assert hydrated["snapshot_id"] == "snapshot-a"
    for node_id in state.active_node_ids:
        assert hydrated_by_id[node_id] == graph.node(node_id).to_dict()


def test_active_state_reuses_prior_working_set_and_stays_bounded():
    runtime = ActiveStateRuntime(
        _graph(),
        "snapshot-a",
        budget=ActiveStateBudget(max_nodes=4, max_edges=4, max_retrievals=4),
    )
    first = runtime.begin_from_node(
        "root",
        "price helper",
        task="trace price history and audit behavior",
        context_budget=_context_budget(),
        max_depth=1,
        beam_width=3,
    )
    second = runtime.continue_from_node(
        first.state,
        "helper",
        "stale history",
        open_questions=("Where is audit behavior triggered?",),
        context_budget=_context_budget(),
        max_depth=2,
        beam_width=3,
    )
    third = runtime.continue_from_node(
        second.state,
        "history",
        "audit log",
        context_budget=_context_budget(),
        max_depth=1,
        beam_width=3,
    )

    assert second.reused_node_ids
    assert third.reused_node_ids
    assert len(third.state.active_node_ids) <= 4
    assert len(third.state.active_edge_ids) <= 4
    assert third.state.step == 3
    assert len(third.state.retrievals) == 3
    assert "Where is audit behavior triggered?" in third.state.open_questions
    assert third.state.cumulative_delivered_tokens >= third.working_context_tokens
    assert third.context_growth_avoided_tokens >= 0


def test_active_state_roundtrips_portable_schema():
    runtime = ActiveStateRuntime(_graph(), "snapshot-a")
    state = runtime.begin_from_node(
        "root",
        "price helper",
        context_budget=_context_budget(),
        max_depth=1,
    ).state

    restored = ActiveState.from_dict(state.to_dict())

    assert restored == state
    assert restored.compact_tokens > 0


def test_active_state_invalidates_when_snapshot_changes():
    first_runtime = ActiveStateRuntime(_graph(), "snapshot-a")
    state = first_runtime.begin_from_node(
        "root",
        "price helper",
        context_budget=_context_budget(),
        max_depth=1,
    ).state

    changed_runtime = ActiveStateRuntime(_graph(), "snapshot-b")

    with pytest.raises(ActiveStateInvalidated, match="snapshot changed"):
        changed_runtime.continue_from_focus(
            state,
            "stale history",
            context_budget=_context_budget(),
        )


def test_explicit_invalidation_blocks_rehydration():
    runtime = ActiveStateRuntime(_graph(), "snapshot-a")
    state = runtime.begin_from_node(
        "root",
        "price helper",
        context_budget=_context_budget(),
        max_depth=1,
    ).state
    invalid = runtime.invalidate(state, "new runtime trace changed task evidence")

    with pytest.raises(ActiveStateInvalidated, match="new runtime trace"):
        runtime.rehydrate(invalid)
