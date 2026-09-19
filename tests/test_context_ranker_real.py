from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.real_benchmark import REAL_BENCHMARK_SCHEMA, run_graph_benchmark
from feynmap.snapshots import RepositorySnapshot
from feynmap.context import StoredSnapshotContext


class FakeProvider:
    name = "fake"

    def evaluate(self, state, questions):
        scores = {"target": 0.98, "helper": 0.75, "noise": 0.02}
        answers = {}
        for index, candidate in enumerate(state["candidates"]):
            answers["candidate_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL, scores[candidate["qualified_name"]]
            )
        return JudgmentResult(
            "fake",
            "fake-v1",
            answers,
            request_id="req-test",
            usage={"input_tokens": 100, "output_tokens": 10},
        )


def _context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "root", qualified_name="root", evidence=evidence),
        SemanticNode("noise", "noise", qualified_name="noise", evidence=evidence),
        SemanticNode("target", "target", qualified_name="target", evidence=evidence),
        SemanticNode("helper", "helper", qualified_name="helper", evidence=evidence),
    ]
    edges = [
        SemanticEdge("e1", "root", "noise", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e2", "root", "target", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e3", "root", "helper", EdgeKind.CALLS, 0.9, evidence),
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


def test_real_benchmark_uses_frozen_relationship_labels_and_real_traversal_order():
    golden = {
        "expected_relationships": [
            {"source": "root", "kind": "calls", "target": "target", "importance": "critical"},
            {"source": "root", "kind": "calls", "target": "helper", "importance": "important"},
        ]
    }
    spec = {
        "schema": REAL_BENCHMARK_SCHEMA,
        "name": "fixture",
        "retrieval": {"depth": 1, "max_nodes": 3, "max_edges": 3, "max_tokens": 2000},
        "tasks": [{"id": "t1", "root": "root", "description": "fix target"}],
    }
    result = run_graph_benchmark(_context(), golden, spec, FakeProvider(), ks=(1, 3))
    task = result["tasks"][0]

    assert task["candidate_count"] == 3
    assert task["golden_essential"] == ["target"]
    assert task["baseline_order"][0] == "noise"
    assert task["reranked_order"][0] == "target"
    assert task["baseline"]["essential_recall@1"] == 0.0
    assert task["reranked"]["essential_recall@1"] == 1.0
    assert task["reranked"]["noise@1"] == 0.0
    assert task["reranked"]["ndcg@3"] > task["baseline"]["ndcg@3"]
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 10}


def test_missing_golden_target_counts_against_end_to_end_recall():
    golden = {
        "expected_relationships": [
            {"source": "root", "kind": "calls", "target": "missing", "importance": "critical"}
        ]
    }
    spec = {
        "schema": REAL_BENCHMARK_SCHEMA,
        "name": "fixture",
        "retrieval": {"depth": 1, "max_nodes": 3, "max_edges": 3, "max_tokens": 2000},
        "tasks": [{"id": "t1", "root": "root", "description": "find missing"}],
    }
    result = run_graph_benchmark(_context(), golden, spec, None, ks=(3,))
    task = result["tasks"][0]
    assert task["retrieval"]["essential_recall"] == 0.0
    assert task["baseline"]["essential_recall@3"] == 0.0
    assert task["baseline"]["missing_essential"] == 1
    assert task["baseline"]["essential_full_recall_min_k"] is None
