from types import SimpleNamespace

import pytest

from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.judgment import GuidedSearchResult, JevGuidedSearch, JudgmentAnswer, JudgmentKind, JudgmentResult


class FakeProvider:
    name = "fake-jev"

    def __init__(self, scores):
        self.scores = dict(scores)
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        answers = {}
        for key, question in questions.items():
            candidate_id = state["candidates"][int(key.split("_")[-1])]["id"]
            answers[key] = JudgmentAnswer(
                kind=JudgmentKind.NOUL,
                value=float(self.scores.get(candidate_id, 0.0)),
            )
        return JudgmentResult(
            provider=self.name,
            model="jev-test",
            answers=answers,
            request_id="req_%d" % len(self.calls),
        )


def _graph():
    root = SemanticNode(id="root", name="Root", kind=NodeKind.FUNCTION)
    alpha = SemanticNode(id="alpha", name="AlphaService", kind=NodeKind.CLASS)
    beta = SemanticNode(id="beta", name="BetaHelper", kind=NodeKind.FUNCTION)
    target = SemanticNode(id="target", name="PaymentReconciler", kind=NodeKind.CLASS)
    noise = SemanticNode(id="noise", name="UnrelatedThing", kind=NodeKind.CLASS)

    edges = [
        SemanticEdge(id="e1", source="root", target="alpha", kind=EdgeKind.CALLS, confidence=1.0),
        SemanticEdge(id="e2", source="root", target="beta", kind=EdgeKind.CALLS, confidence=1.0),
        SemanticEdge(id="e3", source="alpha", target="target", kind=EdgeKind.DEPENDS_ON, confidence=1.0),
        SemanticEdge(id="e4", source="beta", target="noise", kind=EdgeKind.DEPENDS_ON, confidence=1.0),
    ]
    return SemanticGraph(nodes=[root, alpha, beta, target, noise], edges=edges)


def test_node_search_uses_judgment_to_choose_which_branch_to_expand():
    provider = FakeProvider({"alpha": 0.9, "beta": 0.1, "target": 0.95, "noise": 0.01})
    result = JevGuidedSearch(_graph(), provider).from_node(
        "root",
        "find payment reconciliation logic",
        max_depth=2,
        beam_width=1,
    )

    assert isinstance(result, GuidedSearchResult)
    assert [hit.node.id for hit in result.hits] == ["root", "alpha", "target"]
    assert result.trace[0].selected == ["alpha"]
    assert result.trace[1].selected == ["target"]
    assert result.provider == "fake-jev"
    assert result.model == "jev-test"


def test_node_search_respects_direction_and_relationship_filter():
    engine = JevGuidedSearch(_graph())
    result = engine.from_node(
        "target",
        "find callers",
        direction="incoming",
        relationship_kinds=[EdgeKind.DEPENDS_ON],
        max_depth=1,
    )
    assert [hit.node.id for hit in result.hits] == ["target", "alpha"]
    assert [edge.id for edge in result.edges] == ["e3"]


def test_concept_search_finds_lexical_seed_then_expands_with_jev():
    provider = FakeProvider({"target": 0.99, "alpha": 0.8, "root": 0.2})
    result = JevGuidedSearch(_graph(), provider).concept(
        "payment reconciler",
        seed_limit=1,
        max_depth=1,
        beam_width=1,
    )

    assert result.mode == "concept"
    assert [node.id for node in result.roots] == ["target"]
    assert result.trace[0].depth == 0
    assert result.trace[0].selected == ["target"]


def test_offline_fallback_is_deterministic_and_does_not_require_jev():
    result = JevGuidedSearch(_graph()).from_node(
        "root",
        "anything",
        max_depth=1,
        beam_width=2,
    )
    assert [hit.node.id for hit in result.hits] == ["root", "alpha", "beta"]
    assert result.provider is None
    assert result.trace[0].probabilities == {}


def test_invalid_direction_is_rejected():
    with pytest.raises(ValueError, match="direction"):
        JevGuidedSearch(_graph()).from_node("root", "x", direction="sideways")
