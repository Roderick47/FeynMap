from feynmap.context import StoredSnapshotContext
from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.judgment.context_ranker_v1e import _adaptive_selection as adaptive_selection_v1e
from feynmap.judgment.context_ranker_v1h import adaptive_selection_v1h
from feynmap.snapshots import RepositorySnapshot


def _context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "root", qualified_name="root", evidence=evidence),
        SemanticNode("price", "price", qualified_name="price", evidence=evidence),
        SemanticNode("location", "location", qualified_name="location", evidence=evidence),
        SemanticNode("bridge", "renderer", qualified_name="renderer", evidence=evidence),
        SemanticNode("noise1", "query", qualified_name="query", evidence=evidence),
        SemanticNode("noise2", "distance", qualified_name="distance", evidence=evidence),
        SemanticNode("target", "client", qualified_name="client", evidence=evidence),
    ]
    edges = [
        SemanticEdge("e1", "root", "price", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e2", "root", "location", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e3", "root", "bridge", EdgeKind.RENDERS, 0.9, evidence),
        SemanticEdge("e4", "price", "noise1", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e5", "location", "noise2", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e6", "bridge", "target", EdgeKind.LOADS, 0.9, evidence),
    ]
    graph = SemanticGraph(nodes, edges)
    snapshot = RepositorySnapshot(
        snapshot_id="s1",
        repository_key="repo",
        locator="fixture",
        root_hint=".",
        revision="abc",
        content_hash="content",
        graph_hash="graph",
        graph_schema_version="1.0.0",
        analysis_options={},
    )
    return StoredSnapshotContext(snapshot, graph)


def _run(selector):
    context = _context()
    return selector(
        context,
        context.query.resolve("root"),
        "show price reports near the user's location",
        max_depth=2,
        max_candidates=10,
        max_branch_expansions_per_depth=2,
        fallback_branch_expansions=1,
    )


def test_v1h_reserves_structural_exploration_when_lexical_branches_dominate():
    old = _run(adaptive_selection_v1e)
    diversified = _run(adaptive_selection_v1h)

    assert "target" not in old["candidate_ids"]
    assert "target" in diversified["candidate_ids"]

    first = diversified["branch_decisions"][0]["expand"]
    assert {item["selection_mode"] for item in first} == {"semantic", "exploration"}
    assert any(item["candidate"] == "renderer" and item["selection_mode"] == "exploration" for item in first)


def test_v1h_selection_is_label_free_and_deterministic():
    first = _run(adaptive_selection_v1h)
    second = _run(adaptive_selection_v1h)

    assert first["candidate_ids"] == second["candidate_ids"]
    assert first["branch_decisions"] == second["branch_decisions"]
    assert first["stopped_reason"] == "diversified semantic frontier stabilized or depth exhausted"
