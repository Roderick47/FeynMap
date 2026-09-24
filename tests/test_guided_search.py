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



def test_offline_fallback_uses_query_relevance_before_confidence():
    result = JevGuidedSearch(_graph()).from_node(
        "root",
        "beta helper",
        max_depth=1,
        beam_width=1,
    )
    assert [hit.node.id for hit in result.hits] == ["root", "beta"]


def test_allowed_node_filter_bounds_search_candidates():
    result = JevGuidedSearch(_graph()).from_node(
        "root",
        "find payment reconciliation logic",
        max_depth=2,
        beam_width=4,
        allowed_node_ids={"root", "alpha", "target"},
    )
    assert [hit.node.id for hit in result.hits] == ["root", "alpha", "target"]
    assert all("beta" not in step.candidates for step in result.trace)



def test_sparse_beam_prefers_cross_boundary_edge_over_containment_noise():
    root = SemanticNode(id="root2", name="Root2", kind=NodeKind.FUNCTION)
    noise = SemanticNode(id="noise2", name="Noise", kind=NodeKind.CLASS)
    loaded = SemanticNode(id="loaded", name="onboarding.js", kind=NodeKind.FILE)
    graph = SemanticGraph(
        nodes=[root, noise, loaded],
        edges=[
            SemanticEdge(id="contains-noise", source="root2", target="noise2", kind=EdgeKind.CONTAINS, confidence=1.0),
            SemanticEdge(id="loads-script", source="root2", target="loaded", kind=EdgeKind.LOADS, confidence=1.0),
        ],
    )

    result = JevGuidedSearch(graph).from_node(
        "root2",
        "continue through important application boundaries",
        max_depth=1,
        beam_width=1,
    )

    assert [hit.node.id for hit in result.hits] == ["root2", "loaded"]



def test_sparse_search_does_not_use_repository_root_as_global_shortcut():
    repository = SemanticNode(id="repository:root", name="repo", kind=NodeKind.REPOSITORY)
    module = SemanticNode(id="module", name="module", kind=NodeKind.MODULE)
    start = SemanticNode(id="start", name="start", kind=NodeKind.FUNCTION)
    unrelated = SemanticNode(id="unrelated", name="unrelated", kind=NodeKind.FUNCTION)
    graph = SemanticGraph(
        nodes=[repository, module, start, unrelated],
        edges=[
            SemanticEdge(id="repo-module", source="repository:root", target="module", kind=EdgeKind.CONTAINS, confidence=1.0),
            SemanticEdge(id="module-start", source="module", target="start", kind=EdgeKind.CONTAINS, confidence=1.0),
            SemanticEdge(id="repo-unrelated", source="repository:root", target="unrelated", kind=EdgeKind.CONTAINS, confidence=1.0),
        ],
    )

    result = JevGuidedSearch(graph).from_node(
        "start",
        "find relevant application behavior",
        max_depth=3,
        beam_width=8,
    )

    assert "repository:root" not in {hit.node.id for hit in result.hits}
    assert "unrelated" not in {hit.node.id for hit in result.hits}



def test_semantic_path_continuity_preserves_high_value_chain():
    root = SemanticNode(id="chain-root", name="home", kind=NodeKind.FUNCTION)
    template = SemanticNode(id="chain-template", name="home.html", kind=NodeKind.UI_SURFACE)
    base = SemanticNode(id="chain-base", name="base.html", kind=NodeKind.UI_SURFACE)
    target = SemanticNode(id="chain-target", name="onboarding.js", kind=NodeKind.MODULE)
    noise1 = SemanticNode(id="noise-call", name="helper", kind=NodeKind.FUNCTION)
    noise2 = SemanticNode(id="noise-import", name="utility", kind=NodeKind.MODULE)

    graph = SemanticGraph(
        nodes=[root, template, base, target, noise1, noise2],
        edges=[
            SemanticEdge(id="r1", source="chain-root", target="chain-template", kind=EdgeKind.RENDERS, confidence=1.0),
            SemanticEdge(id="r2", source="chain-template", target="chain-base", kind=EdgeKind.EXTENDS, confidence=1.0),
            SemanticEdge(id="r3", source="chain-base", target="chain-target", kind=EdgeKind.LOADS, confidence=1.0),
            SemanticEdge(id="n1", source="chain-root", target="noise-call", kind=EdgeKind.CALLS, confidence=1.0),
            SemanticEdge(id="n2", source="noise-call", target="noise-import", kind=EdgeKind.IMPORTS, confidence=1.0),
        ],
    )

    result = JevGuidedSearch(graph).from_node(
        "chain-root",
        "improve the homepage experience",
        max_depth=3,
        beam_width=1,
    )

    assert [hit.node.id for hit in result.hits] == [
        "chain-root",
        "chain-template",
        "chain-base",
        "chain-target",
    ]
    assert result.hits[-1].path_score > result.hits[1].path_score



def test_cross_boundary_reserve_keeps_multiple_template_dependencies_in_fixed_beam():
    root = SemanticNode(id="reserve-root", name="home", kind=NodeKind.FUNCTION)
    template = SemanticNode(id="reserve-template", name="home.html", kind=NodeKind.UI_SURFACE)
    base = SemanticNode(id="reserve-base", name="base.html", kind=NodeKind.UI_SURFACE)
    include = SemanticNode(id="reserve-include", name="_onboarding.html", kind=NodeKind.UI_SURFACE)
    script = SemanticNode(id="reserve-script", name="onboarding.js", kind=NodeKind.MODULE)
    validation = SemanticNode(id="reserve-validation", name="form-validation.js", kind=NodeKind.MODULE)
    noises = [
        SemanticNode(id="reserve-noise-%d" % index, name="noise%d" % index, kind=NodeKind.FUNCTION)
        for index in range(12)
    ]

    nodes = [root, template, base, include, script, validation] + noises
    edges = [
        SemanticEdge(id="rr1", source=root.id, target=template.id, kind=EdgeKind.RENDERS, confidence=1.0),
        SemanticEdge(id="rr2", source=template.id, target=base.id, kind=EdgeKind.EXTENDS, confidence=1.0),
        SemanticEdge(id="rr3", source=base.id, target=include.id, kind=EdgeKind.RENDERS, confidence=1.0),
        SemanticEdge(id="rr4", source=base.id, target=script.id, kind=EdgeKind.LOADS, confidence=1.0),
        SemanticEdge(id="rr5", source=base.id, target=validation.id, kind=EdgeKind.LOADS, confidence=1.0),
    ]
    for index, noise in enumerate(noises):
        edges.append(
            SemanticEdge(
                id="rn%d" % index,
                source=base.id if index < 6 else template.id,
                target=noise.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            )
        )

    result = JevGuidedSearch(SemanticGraph(nodes=nodes, edges=edges)).from_node(
        root.id,
        "improve homepage price discovery",
        max_depth=3,
        beam_width=8,
    )

    activated = {hit.node.id for hit in result.hits}
    assert include.id in activated
    assert script.id in activated
    assert validation.id in activated
