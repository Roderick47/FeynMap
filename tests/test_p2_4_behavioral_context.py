from pathlib import Path

from feynmap.behavior import BehaviorKind
from feynmap.behavioral_context import BehaviorEvidenceBudget, BehavioralContextBuilder
from feynmap.context_pipeline import SparseContextPipeline
from feynmap.delivery_channels import DeliveryChannelPolicy
from feynmap.engine import FeynMapEngine
from feynmap.judgment.contracts import (
    JudgmentAnswer,
    JudgmentKind,
    JudgmentProvider,
    JudgmentResult,
)
from feynmap.minimal_context import MinimalContextBudget
from feynmap.relevance import JudgmentProviderRelevanceJudge
from feynmap.task_evidence import TaskConditionedEvidencePipeline


ROOT = Path(__file__).resolve().parents[1] / "experiments" / "fixtures" / "p2_3b_fulfillment"


def _graph():
    graph = FeynMapEngine().analyze(str(ROOT), language="auto", framework="none")
    assert not graph.diagnostics.get("errors")
    return graph


def _build(task, *, judge=None, behavior_tokens=2200):
    graph = _graph()
    pipeline = SparseContextPipeline(graph)
    sparse = pipeline.concept(
        task,
        context_budget=MinimalContextBudget(
            max_tokens=3200,
            max_nodes=24,
            max_edges=24,
        ),
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
        seed_limit=8,
        candidate_limit=64,
        max_depth=3,
        beam_width=8,
        max_nodes=64,
        direction="both",
    )
    builder = BehavioralContextBuilder(
        graph,
        ROOT,
        judge=judge,
        budget=BehaviorEvidenceBudget(
            max_tokens=behavior_tokens,
            max_observations=48,
            max_source_chars=5000,
        ),
    )
    return sparse.context, builder.build(task, sparse.context)


def _observations(result):
    return list(result.payload["behavioral_evidence"]["observations"])


def test_reserve_order_envelope_exposes_validation_mutation_and_return_in_source_order():
    task = (
        "How does reserve_order validate stock before changing quantity, "
        "and what does it return after a successful reservation?"
    )
    base, result = _build(task)
    assert base.sufficient is True
    rows = _observations(result)
    reserve = [row for row in rows if row["symbol_id"].endswith("fulfillment.service.reserve_order")]
    summaries = [row["summary"] for row in reserve]
    assert any("ensure_stock" in value for value in summaries)
    assert any("item.quantity -= requested_quantity" in value for value in summaries)
    assert any("return reservation_message" in value for value in summaries)

    ordered = sorted(reserve, key=lambda row: row["order"])
    ensure_position = next(i for i, row in enumerate(ordered) if "ensure_stock" in row["summary"])
    mutation_position = next(i for i, row in enumerate(ordered) if "item.quantity -= requested_quantity" in row["summary"])
    return_position = next(i for i, row in enumerate(ordered) if "return reservation_message" in row["summary"])
    assert ensure_position < mutation_position < return_position
    mutation = next(row for row in reserve if "item.quantity -= requested_quantity" in row["summary"])
    assert "item.quantity" in mutation["source_facts"]["reads"]
    assert "-" in mutation["source_facts"]["operators"]
    assert result.payload["behavioral_evidence"]["grounding"]["source_order_scope"].startswith("ordering is local")


def test_failure_behavior_preserves_condition_raise_and_test_assertions_when_selected():
    task = (
        "Which test demonstrates that an insufficient reserve_order request leaves "
        "stock unchanged, and what behavior does it exercise?"
    )
    _, result = _build(task)
    rows = _observations(result)
    assert any(
        row["kind"] == BehaviorKind.CONDITION.value
        and "requested_quantity > item.quantity" in row["summary"]
        for row in rows
    )
    assert any(
        row["kind"] == BehaviorKind.RAISE.value
        and "InsufficientStock" in row["summary"]
        and "requested_quantity > item.quantity" in row.get("condition", "")
        for row in rows
    )
    assert any(row["kind"] == BehaviorKind.ASSERTION.value for row in rows)
    test_assertion = next(
        row for row in rows
        if row["kind"] == BehaviorKind.ASSERTION.value and "item.quantity == 2" in row["summary"]
    )
    assert 2 in test_assertion["source_facts"]["literals"]


def test_migration_and_default_behavior_exposes_guard_mutation_and_literal_return():
    task = "How does apply_priority_default initialize missing priority values without overwriting existing priority?"
    _, result = _build(task)
    rows = _observations(result)
    assert any("\"priority\" not in row" in row["summary"] for row in rows)
    migration_write = next(
        row for row in rows
        if "row[\"priority\"] = priority_default()" in row["summary"]
        and "\"priority\" not in row" in row.get("condition", "")
    )
    assert migration_write["attributes"]["migration"] is True
    assert "priority" in migration_write["source_facts"]["literals"]
    normal = next(row for row in rows if "return \"normal\"" in row["summary"])
    assert "normal" in normal["source_facts"]["literals"]


def test_cancel_policy_exposes_allowed_status_literals_without_inventing_refund():
    task = "What does cancel_order actually do, which statuses can can_cancel approve, and does this source perform a refund side effect?"
    _, result = _build(task)
    rows = _observations(result)
    allowed = next(
        row for row in rows if "status in {\"queued\", \"packed\"}" in row["summary"]
    )
    assert set(allowed["source_facts"]["literals"]) >= {"queued", "packed"}
    assert not any("refund" in row["summary"].casefold() for row in rows)


def test_javascript_behavior_keeps_exact_normalization_source_witness():
    task = "How does formatShipmentStatus use normalizeStatus, and what transformation does normalizeStatus perform?"
    _, result = _build(task)
    rows = _observations(result)
    # The formatter call is separately represented; the normalizer's return
    # witness must preserve the raw transformation chain itself.
    normalized = next(
        row for row in rows
        if ".trim().toUpperCase()" in str(row.get("source", ""))
    )
    assert {"trim", "toUpperCase"} <= set(normalized["source_facts"]["transforms"])
    assert "String" in normalized["source_facts"]["calls"]
    assert any("normalizeStatus" in row["summary"] for row in rows)


def test_missing_identifier_remains_insufficient_and_behavior_does_not_fabricate_it():
    task = "How does issue_refund send money back after cancel_order?"
    base, result = _build(task)
    assert list(base.unresolved_query_identifiers) == ["issue_refund"]
    assert result.sufficient is False
    assert result.sufficiency.label.value == "needs_expansion"
    assert "issue_refund" in result.sufficiency.missing_dimensions
    assert not any("issue_refund" in row["summary"] for row in _observations(result))


class _AllEssentialProvider(JudgmentProvider):
    @property
    def name(self):
        return "all-essential-test-provider"

    def evaluate(self, state, questions):
        answers = {}
        for key, question in questions.items():
            if key == "sufficiency":
                value = "sufficient"
                probabilities = {"sufficient": 1.0}
            else:
                value = "essential"
                probabilities = {"essential": 1.0}
            answers[key] = JudgmentAnswer(
                kind=JudgmentKind.CHOICE,
                value=value,
                probabilities=probabilities,
                confidence=1.0,
            )
        return JudgmentResult(
            provider=self.name,
            model="test",
            answers=answers,
        )


def test_learned_relevance_can_rank_but_cannot_upgrade_source_evidence_tier():
    judge = JudgmentProviderRelevanceJudge(_AllEssentialProvider())
    _, result = _build(
        "How does formatShipmentStatus use normalizeStatus?",
        judge=judge,
    )
    rows = _observations(result)
    js_rows = [row for row in rows if row["symbol_id"].startswith("javascript:")]
    assert js_rows
    assert all(row["confidence_tier"] == "inferred" for row in js_rows)
    assert all(row["relevance"]["label"] == "essential" for row in rows)


def test_behavior_budget_fails_closed_when_relevant_observations_are_omitted():
    _, result = _build(
        "How does reserve_order validate stock before changing quantity, and what does it return?",
        behavior_tokens=260,
    )
    assert result.omitted_relevant_observations > 0
    assert result.sufficient is False
    assert result.sufficiency.label.value == "needs_expansion"


def test_public_task_conditioned_pipeline_composes_symbol_and_behavior_evidence():
    graph = _graph()
    pipeline = TaskConditionedEvidencePipeline(
        graph,
        ROOT,
        behavior_budget=BehaviorEvidenceBudget(
            max_tokens=2200,
            max_observations=48,
            max_source_chars=5000,
        ),
    )
    task = "How does reserve_order validate stock before changing quantity, and what does it return?"
    result = pipeline.concept(
        task,
        context_budget=MinimalContextBudget(max_tokens=3200, max_nodes=24, max_edges=24),
    )
    assert result.sparse.context.unresolved_query_identifiers == ()
    assert result.payload["behavioral_evidence"]["schema"] == "feynmap.behavioral_evidence.v1"
    assert any(
        row["kind"] == "mutation" and "item.quantity -= requested_quantity" in row["summary"]
        for row in result.payload["behavioral_evidence"]["observations"]
    )
