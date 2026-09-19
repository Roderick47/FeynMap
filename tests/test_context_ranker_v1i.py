from feynmap.context import StoredSnapshotContext
from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.judgment.context_ranker_v1i import adaptive_selection_v1i
from feynmap.snapshots import RepositorySnapshot


def _snapshot(graph):
    return StoredSnapshotContext(
        RepositorySnapshot(
            snapshot_id="s1",
            repository_key="repo",
            locator="fixture",
            root_hint=".",
            revision="abc",
            content_hash="content",
            graph_hash="graph",
            graph_schema_version="1.0.0",
            analysis_options={},
        ),
        graph,
    )


def _boundary_context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "home", language="python", qualified_name="app.home", location=SourceLocation("views.py"), evidence=evidence),
        SemanticNode("prices", "prices", language="python", qualified_name="app.prices", location=SourceLocation("views.py"), evidence=evidence),
        SemanticNode("config", "Config", language="python", qualified_name="app.Config", location=SourceLocation("apps.py"), evidence=evidence),
        SemanticNode("page", "home.html", language="html", qualified_name="templates/home.html", location=SourceLocation("templates/home.html"), evidence=evidence),
        SemanticNode("query", "query", language="python", qualified_name="app.query", location=SourceLocation("queries.py"), evidence=evidence),
        SemanticNode("external", "FrameworkConfig", language="python", qualified_name="framework.Config", evidence=evidence),
        SemanticNode("client", "client.js", language="javascript", qualified_name="static/client.js", location=SourceLocation("static/client.js"), evidence=evidence),
    ]
    edges = [
        SemanticEdge("e1", "root", "prices", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e2", "root", "config", EdgeKind.DEPENDS_ON, 0.9, evidence),
        SemanticEdge("e3", "root", "page", EdgeKind.RENDERS, 0.9, evidence),
        SemanticEdge("e4", "prices", "query", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e5", "config", "external", EdgeKind.EXTENDS, 0.9, evidence),
        SemanticEdge("e6", "page", "client", EdgeKind.LOADS, 0.9, evidence),
    ]
    return _snapshot(SemanticGraph(nodes, edges))


def _continuation_context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "home", language="python", qualified_name="app.home", location=SourceLocation("views.py"), evidence=evidence),
        SemanticNode("page", "home.html", language="html", qualified_name="templates/home.html", location=SourceLocation("templates/home.html"), evidence=evidence),
        SemanticNode("helper", "helper", language="python", qualified_name="app.helper", location=SourceLocation("helper.py"), evidence=evidence),
        SemanticNode("card", "price_card.html", language="html", qualified_name="templates/price_card.html", location=SourceLocation("templates/price_card.html"), evidence=evidence),
        SemanticNode("base", "base.html", language="html", qualified_name="templates/base.html", location=SourceLocation("templates/base.html"), evidence=evidence),
        SemanticNode("formatter", "price_formatter", language="python", qualified_name="app.price_formatter", location=SourceLocation("formatters.py"), evidence=evidence),
        SemanticNode("helper_child", "worker", language="python", qualified_name="app.worker", location=SourceLocation("worker.py"), evidence=evidence),
        SemanticNode("target", "onboarding.js", language="javascript", qualified_name="static/onboarding.js", location=SourceLocation("static/onboarding.js"), evidence=evidence),
    ]
    edges = [
        SemanticEdge("e1", "root", "page", EdgeKind.RENDERS, 0.9, evidence),
        SemanticEdge("e2", "root", "helper", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e3", "page", "card", EdgeKind.RENDERS, 0.9, evidence),
        SemanticEdge("e4", "page", "base", EdgeKind.EXTENDS, 0.9, evidence),
        SemanticEdge("e5", "card", "formatter", EdgeKind.INVOKES, 0.9, evidence),
        SemanticEdge("e6", "helper", "helper_child", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e7", "base", "target", EdgeKind.LOADS, 0.9, evidence),
    ]
    return _snapshot(SemanticGraph(nodes, edges))


def _run(context, description, max_depth=3):
    return adaptive_selection_v1i(
        context,
        context.query.resolve("app.home"),
        description,
        max_depth=max_depth,
        max_candidates=20,
        max_branch_expansions_per_depth=2,
        fallback_branch_expansions=1,
    )


def test_v1i_prefers_repository_local_boundary_over_external_framework_dead_end():
    result = _run(
        _boundary_context(),
        "show prices near the user's location",
        max_depth=2,
    )

    selected = result["branch_decisions"][0]["expand"]
    assert any(item["candidate"] == "app.prices" and item["selection_mode"] == "semantic" for item in selected)
    page = next(item for item in selected if item["candidate"] == "templates/home.html")
    assert page["selection_mode"] == "structural_bridge"
    assert page["cross_language_from_parent"] is True
    assert page["local_children"] == 1
    assert "client" in result["candidate_ids"]
    assert not any(item["candidate"] == "app.Config" for item in selected)


def test_v1i_continues_through_composition_bridge_when_semantic_child_is_stronger():
    result = _run(
        _continuation_context(),
        "improve the price card on the home page",
        max_depth=3,
    )

    second = result["branch_decisions"][1]["expand"]
    assert any(item["candidate"] == "templates/price_card.html" and item["selection_mode"] == "semantic" for item in second)
    base = next(item for item in second if item["candidate"] == "templates/base.html")
    assert base["selection_mode"] == "structural_bridge"
    assert base["relationship"] == EdgeKind.EXTENDS.value
    assert "target" in result["candidate_ids"]


def test_v1i_is_deterministic_and_label_free():
    context = _continuation_context()
    first = _run(context, "improve the price card on the home page")
    second = _run(_continuation_context(), "improve the price card on the home page")

    assert first["candidate_ids"] == second["candidate_ids"]
    assert first["branch_decisions"] == second["branch_decisions"]
