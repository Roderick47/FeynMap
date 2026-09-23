from feynmap.context import StoredSnapshotContext
from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.context_ranker_v1d import (
    V1D_SCHEMA,
    adaptive_cutoff,
    run_graph_experiment,
)
from feynmap.snapshots import RepositorySnapshot


class FakeProvider:
    name = "fake"

    def evaluate(self, state, questions):
        scores = {"target": 0.98, "helper": 0.80, "noise": 0.02, "caller": 0.1}
        answers = {}
        for index, candidate in enumerate(state["grounded_context"]["candidates"]):
            label = candidate.get("qualified_name") or candidate["id"]
            answers["candidate_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL, scores[label]
            )
        return JudgmentResult(
            "fake",
            "fake-v1",
            answers,
            request_id="req-v1d",
            usage={"input_tokens": 40, "output_tokens": 4},
        )


def _context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "root", qualified_name="root", evidence=evidence),
        SemanticNode("noise", "noise", qualified_name="noise", evidence=evidence),
        SemanticNode("target", "target", qualified_name="target", evidence=evidence),
        SemanticNode("helper", "helper", qualified_name="helper", evidence=evidence),
        SemanticNode("caller", "caller", qualified_name="caller", evidence=evidence),
    ]
    edges = [
        SemanticEdge("e0", "root", "noise", EdgeKind.CONTAINS, 0.9, evidence),
        SemanticEdge("e1", "root", "target", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e2", "root", "helper", EdgeKind.DEPENDS_ON, 0.9, evidence),
        SemanticEdge("e3", "caller", "root", EdgeKind.CALLS, 0.9, evidence),
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


def _golden():
    return {
        "expected_relationships": [
            {"source": "root", "kind": "calls", "target": "target", "importance": "critical"},
            {"source": "root", "kind": "depends_on", "target": "helper", "importance": "important"},
        ]
    }


def _spec():
    return {
        "schema": V1D_SCHEMA,
        "name": "fixture",
        "retrieval": {"depth": 1, "max_edges": 10, "max_tokens": 2000},
        "adaptive": {"minimum_candidates": 1, "maximum_candidates": 4},
        "comparison_budgets": [1, 2, 4],
        "jev_comparison_budgets": [2],
        "tasks": [{"id": "t1", "root": "root", "description": "fix target"}],
    }


def test_adaptive_cutoff_tracks_outgoing_behavior_not_incoming_or_containment():
    context = _context()
    bundle = context.context_bundle(
        "root",
        depth=1,
    )
    decision = adaptive_cutoff(
        context,
        "root",
        bundle["nodes"],
        minimum=1,
        ceiling=4,
    )

    assert decision["behavioral_target_count"] == 2
    assert set(decision["covered_behavioral_targets"]) == {"target", "helper"}
    assert "caller" not in decision["covered_behavioral_targets"]
    assert "noise" not in decision["covered_behavioral_targets"]
    assert decision["saturated"] is False
    assert decision["cutoff"] >= 2


def test_adaptive_experiment_preserves_golden_recall_and_uses_no_labels_for_cutoff():
    result = run_graph_experiment(_context(), _golden(), _spec(), FakeProvider(), ks=(1, 2, 4))
    task = result["tasks"][0]

    assert task["adaptive"]["retrieval"]["relevant_recall"] == 1.0
    assert task["adaptive"]["decision"]["behavioral_coverage"] == 1.0
    assert result["adaptive_summary"]["mean_relevant_recall"] == 1.0
    assert result["adaptive_summary"]["usage"] == {"input_tokens": 40, "output_tokens": 4}
    assert any(row["candidate_budget"] == 2 and "reranked" in row for row in task["fixed"])


def test_adaptive_cutoff_saturates_when_ceiling_cannot_cover_behavioral_targets():
    context = _context()
    bundle = context.context_bundle(
        "root",
        depth=1,
        budget=None,
    )
    decision = adaptive_cutoff(
        context,
        "root",
        bundle["nodes"][:1],
        minimum=1,
        ceiling=1,
    )

    assert decision["saturated"] is True
    assert decision["cutoff"] == 1
    assert decision["missing_behavioral_targets"]
