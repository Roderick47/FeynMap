from feynmap.context import StoredSnapshotContext
from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.context_ranker_v1c import (
    V1C_SCHEMA,
    build_compact_state,
    build_v1b_style_state,
    run_graph_sweep,
)
from feynmap.snapshots import RepositorySnapshot


class CapturingProvider:
    name = "fake"

    def __init__(self):
        self.states = []

    def evaluate(self, state, questions):
        self.states.append(state)
        scores = {"target": 0.98, "helper": 0.80, "noise": 0.02}
        answers = {}
        candidates = state["grounded_context"]["candidates"]
        for index, candidate in enumerate(candidates):
            label = candidate.get("qualified_name") or candidate["id"]
            answers["candidate_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL, scores[label]
            )
        return JudgmentResult(
            "fake",
            "fake-v1",
            answers,
            request_id="req-v1c",
            usage={"input_tokens": 50, "output_tokens": 5},
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


def _golden():
    return {
        "expected_relationships": [
            {"source": "root", "kind": "calls", "target": "target", "importance": "critical"},
            {"source": "root", "kind": "calls", "target": "helper", "importance": "important"},
        ]
    }


def _spec():
    return {
        "schema": V1C_SCHEMA,
        "name": "fixture",
        "candidate_budgets": [3, 2, 1],
        "retrieval": {"depth": 1, "max_edges": 3, "max_tokens": 2000},
        "tasks": [{"id": "t1", "root": "root", "description": "fix target"}],
    }


def test_compact_state_is_smaller_and_drops_verbose_evidence():
    context = _context()
    bundle = context.context_bundle(
        "root",
        depth=1,
    )
    candidates = list(bundle["nodes"])
    task = {"description": "fix target"}
    compact = build_compact_state(task, bundle, candidates)
    full = build_v1b_style_state(task, bundle, candidates)

    assert "evidence" not in compact["grounded_context"]["candidates"][0]
    assert "confidence" not in compact["grounded_context"]["candidates"][0]
    assert "grounding" not in compact["grounded_context"]
    assert len(str(compact)) < len(str(full))


def test_v1c_sweeps_candidate_budgets_and_records_recall_loss():
    provider = CapturingProvider()
    result = run_graph_sweep(_context(), _golden(), _spec(), provider, ks=(1, 3))

    assert [row["candidate_budget"] for row in result["budgets"]] == [3, 2, 1]
    assert result["budgets"][0]["retrieval"]["mean_relevant_recall"] == 1.0
    assert result["budgets"][0]["reranked"]["reciprocal_rank"] == 1.0
    assert result["budgets"][0]["estimated_state_tokens"]["reduction"] > 0
    assert result["budgets"][0]["usage"] == {"input_tokens": 50, "output_tokens": 5}

    # The one-candidate budget cannot contain both frozen relevant targets.
    assert result["budgets"][-1]["retrieval"]["mean_relevant_recall"] < 1.0


def test_compact_provider_state_contains_only_bounded_structural_context():
    provider = CapturingProvider()
    run_graph_sweep(_context(), _golden(), _spec(), provider, ks=(1,))
    state = provider.states[0]

    assert set(state) == {"task", "grounded_context"}
    assert set(state["grounded_context"]) == {
        "root",
        "candidates",
        "relationships",
        "omissions",
    }
    assert all(
        "evidence" not in candidate
        for candidate in state["grounded_context"]["candidates"]
    )
