from feynmap.context import StoredSnapshotContext
from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.context_ranker_v1e import (
    V1E_SCHEMA,
    build_frontier_state,
    run_graph_experiment,
)
from feynmap.snapshots import RepositorySnapshot


class FakeProvider:
    name = "fake"

    def evaluate(self, state, questions):
        answers = {}
        for index, candidate in enumerate(state["grounded_context"]["candidates"]):
            label = candidate.get("qualified_name") or candidate["id"]
            score = 0.99 if label == "target" else 0.8 if label in {"bridge", "middle"} else 0.05
            answers["candidate_%d" % index] = JudgmentAnswer(JudgmentKind.NOUL, score)
        return JudgmentResult(
            "fake",
            "fake-v1",
            answers,
            request_id="req-v1e",
            usage={"input_tokens": 50, "output_tokens": 5},
        )


def _context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "root", qualified_name="root", evidence=evidence),
        SemanticNode("bridge", "bridge", qualified_name="bridge", evidence=evidence),
        SemanticNode("middle", "middle", qualified_name="middle", evidence=evidence),
        SemanticNode("target", "target", qualified_name="target", evidence=evidence),
        SemanticNode("noise", "noise", qualified_name="noise", evidence=evidence),
        SemanticNode("noise2", "noise2", qualified_name="noise2", evidence=evidence),
        SemanticNode("noise3", "noise3", qualified_name="noise3", evidence=evidence),
    ]
    edges = [
        SemanticEdge("e1", "root", "bridge", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e2", "bridge", "middle", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e3", "middle", "target", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e4", "root", "noise", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e5", "noise", "noise2", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e6", "noise2", "noise3", EdgeKind.CALLS, 0.9, evidence),
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


def _spec():
    return {
        "schema": V1E_SCHEMA,
        "name": "fixture",
        "retrieval": {
            "max_depth": 3,
            "direct_max_candidates": 10,
            "adaptive_max_candidates": 10,
            "naive_max_candidates": 10,
        },
        "adaptive": {
            "max_branch_expansions_per_depth": 1,
            "fallback_branch_expansions": 1,
        },
        "tasks": [
            {
                "id": "t1",
                "root": "root",
                "description": "trace bridge path to target",
                "relevant": ["bridge", "middle", "target"],
                "essential": ["target"],
            }
        ],
    }


def test_v1e_exposes_direct_false_completeness_and_recovers_transitive_target():
    result = run_graph_experiment(_context(), _spec())
    task = result["tasks"][0]

    assert task["essential_shortest_depth"]["target"] == 3
    assert task["direct"]["declared_complete"] is True
    assert task["direct"]["false_complete"] is True
    assert task["direct"]["retrieval"]["essential_recall"] == 0.0
    assert task["naive"]["retrieval"]["essential_recall"] == 1.0
    assert task["adaptive"]["retrieval"]["essential_recall"] == 1.0
    assert result["false_completeness"]["rate"] == 1.0


def test_adaptive_frontier_uses_fewer_candidates_than_naive_on_irrelevant_branch():
    result = run_graph_experiment(_context(), _spec())
    task = result["tasks"][0]

    assert task["adaptive"]["candidate_count"] < task["naive"]["candidate_count"]
    assert task["adaptive_recovery"]["recovered_essential_count"] == 1
    assert task["adaptive_recovery"]["marginal_recovery_efficiency"] is not None


def test_frontier_state_keeps_candidate_to_candidate_path_edges():
    result = run_graph_experiment(_context(), _spec(), FakeProvider())
    task = result["tasks"][0]

    assert task["adaptive"]["reranked_order"][0] == "target"
    assert task["adaptive"]["usage"] == {"input_tokens": 50, "output_tokens": 5}
    provenance = task["adaptive"]["provenance"]
    assert any(item["candidate"] == "target" and item["depth"] == 3 for item in provenance)


def test_v1e_rejects_direct_essential_labels():
    spec = _spec()
    spec["tasks"][0]["essential"] = ["bridge"]
    try:
        run_graph_experiment(_context(), spec)
    except ValueError as exc:
        assert "must be transitive" in str(exc)
    else:
        raise AssertionError("expected direct essential label to be rejected")
