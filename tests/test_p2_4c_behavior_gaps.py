"""P2.4c development regressions from the preserved P2.4b misses.

These tests intentionally reuse the now-seen P2.4b billing fixture only as a
development regression set. They do not revise the frozen 13/15 P2.4b result.
"""
from pathlib import Path

from feynmap.behavioral_context import BehaviorEvidenceBudget
from feynmap.behavioral_delivery import BehavioralSymbolContinuation
from feynmap.context import estimate_tokens
from feynmap.core import (
    EdgeKind,
    Evidence,
    EvidenceKind,
    NodeKind,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
    SourceLocation,
)
from feynmap.delivery_channels import DeliveryChannelPolicy
from feynmap.engine import FeynMapEngine
from feynmap.judgment.search import GuidedSearchResult, SearchHit
from feynmap.minimal_context import MinimalContextBudget, MinimalContextPacker
from feynmap.task_evidence import TaskConditionedEvidencePipeline


ROOT = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "fixtures"
    / "p2_4b_billing"
)


def _billing_graph():
    graph = FeynMapEngine().analyze(str(ROOT), language="auto", framework="none")
    assert not graph.diagnostics.get("errors")
    return graph


def _pipeline():
    graph = _billing_graph()
    return graph, TaskConditionedEvidencePipeline(
        graph,
        ROOT,
        behavior_budget=BehaviorEvidenceBudget(
            max_tokens=2200,
            max_observations=48,
            max_source_chars=5000,
        ),
    )


def _run(task):
    graph, pipeline = _pipeline()
    result = pipeline.concept(
        task,
        context_budget=MinimalContextBudget(
            max_tokens=3200,
            max_nodes=24,
            max_edges=24,
        ),
        seed_limit=8,
        candidate_limit=64,
        max_depth=3,
        beam_width=8,
        max_nodes=64,
        direction="both",
    )
    return graph, result


def _selected_names(graph, result):
    return {
        graph.node(node_id).name
        for node_id in result.sparse.context.selected_node_ids
        if graph.node(node_id) is not None
    }


def _behavior_rows(result):
    return result.payload["behavioral_evidence"]["observations"]


def test_natural_language_test_query_keeps_activated_validation_dependency():
    task = (
        "Which test shows that an overpayment is rejected before invoice state "
        "changes, and what concrete values does it verify?"
    )
    graph, result = _run(task)
    names = _selected_names(graph, result)

    # P2.4b proved this symbol was activated but lost by S3 symbol delivery.
    # P2.4c may retain it only because the real activated CALLS chain exists.
    assert "test_overpayment_leaves_balance_unchanged" in names
    assert "apply_payment" in names
    assert "ensure_payment_allowed" in names
    assert result.continuation.added_node_ids
    assert result.sparse.context.delivered_tokens <= 3200

    rows = _behavior_rows(result)
    assert any(
        row["kind"] == "condition"
        and "payment_cents > outstanding_cents" in row["summary"]
        for row in rows
    )
    assert any(
        row["kind"] == "raise"
        and "OverpaymentError" in row["summary"]
        and "payment_cents > outstanding_cents" in row.get("condition", "")
        for row in rows
    )


def test_test_task_keeps_named_wrapper_return_not_only_nested_call():
    task = (
        "What does retry_payment delegate to, and exactly which statuses are "
        "retryable according to can_retry and its test?"
    )
    _, result = _run(task)
    rows = _behavior_rows(result)
    retry_rows = [
        row for row in rows
        if row["symbol_id"].endswith("billing.service.retry_payment")
    ]
    assert any(
        row["kind"] == "call" and "can_retry(status)" in row["summary"]
        for row in retry_rows
    )
    returned = next(
        row for row in retry_rows
        if row["kind"] == "return" and "return can_retry(status)" in row["summary"]
    )
    assert returned["task_dimension_witness"] is True
    assert result.behavioral.behavior_tokens <= 2200


def test_missing_capture_card_remains_unresolved_after_behavioral_continuation():
    task = "How does capture_card charge the customer before apply_payment runs?"
    graph, result = _run(task)
    assert list(result.sparse.context.unresolved_query_identifiers) == ["capture_card"]
    assert result.sufficient is False
    assert "capture_card" not in _selected_names(graph, result)
    assert not any(
        "capture_card" in row["summary"]
        for row in _behavior_rows(result)
    )


def _source_node(identifier, name, path):
    location = SourceLocation(path, line=1)
    return SemanticNode(
        id=identifier,
        name=name,
        qualified_name=name,
        kind=NodeKind.FUNCTION,
        language="python",
        location=location,
        evidence=[
            Evidence(
                EvidenceKind.STATIC,
                "fixture.definition",
                "source declaration",
                location,
                1.0,
            )
        ],
    )


def _search_with_edge(edge):
    source = _source_node("test", "test_behavior", "tests/test_behavior.py")
    wrapper = _source_node("wrapper", "run_behavior", "service.py")
    dependency = _source_node("dependency", "validate_behavior", "policy.py")
    graph = SemanticGraph(nodes=[source, wrapper, dependency], edges=[edge])
    search = GuidedSearchResult(
        mode="concept",
        query="Which test proves invalid behavior is rejected?",
        roots=[source],
        hits=[
            SearchHit(source, depth=0),
            SearchHit(wrapper, depth=1),
            SearchHit(dependency, depth=2),
        ],
        edges=[edge],
        trace=[],
        provider=None,
        model=None,
        exhausted=True,
        truncated=False,
    )
    return graph, search


def test_continuation_never_promotes_ai_inferred_relationship():
    source = _source_node("test", "test_behavior", "tests/test_behavior.py")
    dependency = _source_node("dependency", "validate_behavior", "policy.py")
    edge = SemanticEdge(
        id="guess",
        source=source.id,
        target=dependency.id,
        kind=EdgeKind.CALLS,
        confidence=0.6,
        evidence=[
            Evidence(
                EvidenceKind.AI_INFERENCE,
                "fixture.guess",
                "not a source witness",
                SourceLocation("tests/test_behavior.py", line=2),
                0.6,
            )
        ],
    )
    graph = SemanticGraph(nodes=[source, dependency], edges=[edge])
    search = GuidedSearchResult(
        mode="concept",
        query="Which test proves invalid behavior is rejected?",
        roots=[source],
        hits=[SearchHit(source, depth=0), SearchHit(dependency, depth=1)],
        edges=[edge],
        trace=[], provider=None, model=None, exhausted=True, truncated=False,
    )
    budget = MinimalContextBudget(max_tokens=1600, max_nodes=12, max_edges=12)
    base = MinimalContextPacker(graph).pack(
        search,
        budget=budget,
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
    )
    continued = BehavioralSymbolContinuation(graph).extend(
        search.query,
        search,
        base,
        budget=budget,
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
    )
    assert continued.added_node_ids == ()
    assert continued.added_edge_ids == ()
    assert "guess" not in continued.context.selected_edge_ids


def test_continuation_cannot_add_node_absent_from_activation():
    source = _source_node("source", "run_behavior", "service.py")
    hidden = _source_node("hidden", "validate_behavior", "policy.py")
    edge = SemanticEdge(
        id="real-call",
        source=source.id,
        target=hidden.id,
        kind=EdgeKind.CALLS,
        confidence=1.0,
        evidence=[
            Evidence(
                EvidenceKind.STATIC,
                "fixture.call",
                "real source call",
                SourceLocation("service.py", line=2),
                1.0,
            )
        ],
    )
    graph = SemanticGraph(nodes=[source, hidden], edges=[edge])
    # The graph knows hidden, but S2 did not activate it and the search result
    # contains neither its hit nor the relationship. P2.4 must not discover it.
    search = GuidedSearchResult(
        mode="concept",
        query="How does run_behavior work?",
        roots=[source],
        hits=[SearchHit(source, depth=0)],
        edges=[],
        trace=[], provider=None, model=None, exhausted=True, truncated=False,
    )
    budget = MinimalContextBudget(max_tokens=1600, max_nodes=12, max_edges=12)
    base = MinimalContextPacker(graph).pack(
        search,
        budget=budget,
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
    )
    continued = BehavioralSymbolContinuation(graph).extend(
        search.query,
        search,
        base,
        budget=budget,
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
    )
    assert "hidden" not in continued.context.selected_node_ids
    assert continued.added_node_ids == ()


def test_continuation_never_escapes_original_sparse_budget():
    task = (
        "Which test shows that an overpayment is rejected before invoice state "
        "changes, and what concrete values does it verify?"
    )
    graph = _billing_graph()
    pipeline = TaskConditionedEvidencePipeline(graph, ROOT)
    budget = MinimalContextBudget(max_tokens=1100, max_nodes=5, max_edges=5)
    result = pipeline.concept(task, context_budget=budget)
    assert result.sparse.context.delivered_tokens <= budget.max_tokens
    assert result.sparse.context.delivered_nodes <= budget.max_nodes
    assert len(result.sparse.context.selected_edge_ids) <= budget.max_edges
    assert estimate_tokens(result.sparse.context.payload) == result.sparse.context.delivered_tokens
