from feynmap.context import StoredSnapshotContext
from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.context_ranker_v1f import (
    V1F_SCHEMA,
    _file_metrics,
    _validate_spec,
    run_graph_task,
)
from feynmap.snapshots import FileFingerprint, RepositorySnapshot


class FakeProvider:
    name = "fake"

    def evaluate(self, state, questions):
        answers = {}
        for index, candidate in enumerate(state["grounded_context"]["candidates"]):
            label = candidate.get("qualified_name") or candidate["id"]
            score = 0.99 if label == "changed_handler" else 0.7 if label == "bridge" else 0.05
            answers["candidate_%d" % index] = JudgmentAnswer(JudgmentKind.NOUL, score)
        return JudgmentResult(
            "fake",
            "fake-v1",
            answers,
            request_id="req-v1f",
            usage={"input_tokens": 80, "output_tokens": 8},
        )


def _context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode("root", "root", qualified_name="root", location=SourceLocation("entry.py"), evidence=evidence),
        SemanticNode("bridge", "bridge", qualified_name="bridge", location=SourceLocation("bridge.py"), evidence=evidence),
        SemanticNode("changed", "changed_handler", qualified_name="changed_handler", location=SourceLocation("changed.py"), evidence=evidence),
        SemanticNode("noise", "noise", qualified_name="noise", location=SourceLocation("noise.py"), evidence=evidence),
    ]
    edges = [
        SemanticEdge("e1", "root", "bridge", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e2", "bridge", "changed", EdgeKind.CALLS, 0.9, evidence),
        SemanticEdge("e3", "root", "noise", EdgeKind.CALLS, 0.9, evidence),
    ]
    graph = SemanticGraph(nodes, edges)
    snapshot = RepositorySnapshot(
        snapshot_id="s1",
        repository_key="repo",
        locator="fixture",
        root_hint=".",
        revision="before",
        content_hash="content",
        graph_hash="graph",
        graph_schema_version="1.0.0",
        analysis_options={},
        files=[
            FileFingerprint("entry.py", "1", 1),
            FileFingerprint("bridge.py", "2", 1),
            FileFingerprint("changed.py", "3", 1),
            FileFingerprint("noise.py", "4", 1),
        ],
    )
    return StoredSnapshotContext(snapshot, graph)


def _task():
    return {
        "id": "historical",
        "source_pr": 1,
        "pre_fix_revision": "before",
        "root": "root",
        "description": "Trace the bridge behavior that should update the changed handler.",
        "gold_changed_files": ["changed.py", "new_signal.py"],
    }


def _retrieval():
    return {
        "max_depth": 3,
        "direct_max_candidates": 10,
        "adaptive_max_candidates": 10,
        "naive_max_candidates": 10,
    }


def _adaptive():
    return {
        "max_branch_expansions_per_depth": 1,
        "fallback_branch_expansions": 1,
    }


def test_v1f_separates_novel_files_from_retrieval_ground_truth():
    result = run_graph_task(_context(), _task(), _retrieval(), _adaptive())
    assert result["gold_existing_files"] == ["changed.py"]
    assert result["gold_novel_files"] == ["new_signal.py"]
    assert result["direct"]["baseline"]["recall@10"] == 0.0
    assert result["adaptive"]["baseline"]["recall@10"] == 1.0
    assert result["adaptive"]["baseline"]["path_recall@10"] == 1.0


def test_v1f_frozen_jev_reranker_improves_file_localization():
    result = run_graph_task(
        _context(), _task(), _retrieval(), _adaptive(), FakeProvider()
    )
    adaptive = result["adaptive"]
    assert adaptive["usage"] == {"input_tokens": 80, "output_tokens": 8}
    assert adaptive["reranked_file_order"][:2] == ["entry.py", "changed.py"]
    assert adaptive["reranked"]["full_recall_min_k"] < adaptive["baseline"]["full_recall_min_k"]


def test_file_metrics_deduplicate_and_measure_noise():
    metrics = _file_metrics(
        ["entry.py", "noise.py", "changed.py", "changed.py"],
        {"changed.py"},
        ks=(1, 3),
        path_backed_files={"changed.py"},
    )
    assert metrics["file_count"] == 3
    assert metrics["recall@1"] == 0.0
    assert metrics["recall@3"] == 1.0
    assert metrics["path_recall@3"] == 1.0
    assert metrics["full_recall_min_k"] == 3


def test_v1f_rejects_gold_path_leakage_in_task_description():
    spec = {
        "schema": V1F_SCHEMA,
        "retrieval": _retrieval(),
        "adaptive": _adaptive(),
        "tasks": [
            {
                "id": "leak",
                "source_pr": 1,
                "pre_fix_revision": "abc",
                "root": "root",
                "description": "Change changed.py to fix the bug.",
                "gold_changed_files": ["changed.py"],
            }
        ],
    }
    try:
        _validate_spec(spec)
    except ValueError as exc:
        assert "leaks gold file path" in str(exc)
    else:
        raise AssertionError("expected task-description leakage to be rejected")
