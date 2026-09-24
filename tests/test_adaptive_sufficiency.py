from feynmap.adaptive import AdaptiveSparseSearch
from feynmap.core import EdgeKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionIndex
from feynmap.sufficiency import SufficiencyEvaluator
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult


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
        direct_stop_coverage=1.0,
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
    assert first.route == second.route
    assert first.route is None



def test_sufficiency_tracks_marginal_information_gain_by_depth():
    root = _node("gain-root", "home", "views.py")
    first = _node("gain-first", "price", "views.py")
    second = _node("gain-second", "history", "models.py")
    graph = SemanticGraph(
        nodes=[root, first, second],
        edges=[
            SemanticEdge(
                id="gain-1",
                source=root.id,
                target=first.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            SemanticEdge(
                id="gain-2",
                source=first.id,
                target=second.id,
                kind=EdgeKind.DEPENDS_ON,
                confidence=1.0,
            ),
        ],
    )

    adaptive = AdaptiveSparseSearch(graph, region_limit=2)
    result = adaptive.from_node(
        root.id,
        "price history",
        max_depth=2,
        beam_width=2,
        max_nodes=8,
    )

    gains = result.local_sufficiency.marginal_gain_by_depth
    assert set(gains) == {0, 1, 2}
    assert gains[1] > 0
    assert gains[2] > 0



class _FakeProvider:
    name = "fake-jev"

    def __init__(self):
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        answers = {}
        for key, question in questions.items():
            candidate_id = state["candidates"][int(key.split("_")[-1])]["id"]
            score = 1.0 if "target" in candidate_id or "alpha" in candidate_id else 0.0
            answers[key] = JudgmentAnswer(
                kind=JudgmentKind.NOUL,
                value=score,
            )
        return JudgmentResult(
            provider=self.name,
            model="jev-test",
            answers=answers,
            request_id="adaptive-%d" % len(self.calls),
        )


def test_adaptive_search_escalates_to_provider_only_after_deterministic_stages():
    root = _node("jev-root", "root", "app.py")
    alpha = _node("jev-alpha", "alpha", "alpha.py")
    beta = _node("jev-beta", "beta", "beta.py")
    target = _node("jev-target", "target", "target.py")
    graph = SemanticGraph(
        nodes=[root, alpha, beta, target],
        edges=[
            SemanticEdge(
                id="jev-a",
                source=root.id,
                target=alpha.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            SemanticEdge(
                id="jev-b",
                source=root.id,
                target=beta.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            SemanticEdge(
                id="jev-target-edge",
                source=alpha.id,
                target=target.id,
                kind=EdgeKind.DEPENDS_ON,
                confidence=1.0,
            ),
        ],
    )
    provider = _FakeProvider()
    evaluator = SufficiencyEvaluator(
        graph,
        region_index=RegionIndex(graph),
        direct_stop_coverage=1.0,
        min_query_coverage=1.0,
        min_score=1.0,
    )

    result = AdaptiveSparseSearch(
        graph,
        provider=provider,
        region_limit=2,
        sufficiency=evaluator,
    ).from_node(
        root.id,
        "target reconciliation",
        max_depth=2,
        beam_width=1,
        max_nodes=8,
    )

    assert result.stage == "jev"
    assert result.escalations == ("region", "jev")
    assert provider.calls
    assert result.search.provider == "fake-jev"
