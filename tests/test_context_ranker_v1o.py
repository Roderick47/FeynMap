from feynmap.context import StoredSnapshotContext
from feynmap.core import (
    EdgeKind,
    Evidence,
    EvidenceKind,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
    SourceLocation,
)
from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.context_ranker_v1o import run_graph_task_v1o
from feynmap.judgment.ranking import baseline_rank
from feynmap.judgment.repair_role_v1j import REPAIR_ROLES, ROLE_PROMPT
from feynmap.snapshots import FileFingerprint, RepositorySnapshot


class TwoPassProvider:
    name = "two-pass-fixture"

    def __init__(self):
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        baseline = baseline_rank(state["grounded_context"]["candidates"])
        answers = {}
        role_call = all(key.startswith("role_") for key in questions)
        for index, item in enumerate(baseline):
            name = item.candidate.get("qualified_name") or item.candidate_id
            if role_call:
                role = {
                    "changed_handler": "implementation_target",
                    "bridge": "structural_bridge",
                    "noise": "incidental_context",
                }.get(name, "supporting_context")
                answers["role_%d" % index] = JudgmentAnswer(
                    JudgmentKind.CHOICE,
                    role,
                    probabilities={
                        candidate_role: (0.91 if candidate_role == role else 0.03)
                        for candidate_role in REPAIR_ROLES
                    },
                )
            else:
                probability = {
                    "changed_handler": 0.97,
                    "bridge": 0.72,
                    "noise": 0.08,
                }.get(name, 0.6)
                answers["candidate_%d" % index] = JudgmentAnswer(
                    JudgmentKind.NOUL, probability
                )
        return JudgmentResult(
            provider=self.name,
            model="fixture-v1",
            answers=answers,
            request_id="role-request" if role_call else "relevance-request",
            usage=(
                {"input_tokens": 100, "output_tokens": 20}
                if role_call
                else {"input_tokens": 80, "output_tokens": 8}
            ),
        )


def _context():
    evidence = [Evidence(EvidenceKind.STATIC, "fixture", confidence=0.9)]
    nodes = [
        SemanticNode(
            "root",
            "root",
            qualified_name="root",
            location=SourceLocation("entry.py"),
            evidence=evidence,
        ),
        SemanticNode(
            "bridge",
            "bridge",
            qualified_name="bridge",
            location=SourceLocation("bridge.py"),
            evidence=evidence,
        ),
        SemanticNode(
            "changed",
            "changed_handler",
            qualified_name="changed_handler",
            location=SourceLocation("changed.py"),
            evidence=evidence,
        ),
        SemanticNode(
            "noise",
            "noise",
            qualified_name="noise",
            location=SourceLocation("noise.py"),
            evidence=evidence,
        ),
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


def _task(gold="changed.py"):
    return {
        "id": "historical-shadow",
        "source_pr": 1,
        "pre_fix_revision": "before",
        "root": "root",
        "description": "Repair the changed handler reached through the entry flow.",
        "gold_changed_files": [gold],
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
        "max_branch_expansions_per_depth": 2,
        "fallback_branch_expansions": 1,
    }


def test_v1o_keeps_relevance_and_role_provider_calls_separate():
    provider = TwoPassProvider()
    result = run_graph_task_v1o(
        _context(), _task(), _retrieval(), _adaptive(), provider
    )
    assert len(provider.calls) == 2
    relevance_questions = provider.calls[0][1]
    role_questions = provider.calls[1][1]
    assert all(key.startswith("candidate_") for key in relevance_questions)
    assert all(key.startswith("role_") for key in role_questions)
    assert result["adaptive"]["usage"] == {
        "input_tokens": 80,
        "output_tokens": 8,
    }
    shadow = result["adaptive"]["role_shadow"]
    assert shadow["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert shadow["request_id"] == "role-request"


def test_v1o_applies_frozen_role_policy_without_changing_production_order():
    provider = TwoPassProvider()
    result = run_graph_task_v1o(
        _context(), _task(), _retrieval(), _adaptive(), provider
    )
    adaptive = result["adaptive"]
    relevance_order = list(adaptive["reranked_file_order"])
    shadow = adaptive["role_shadow"]
    assert shadow["production_policy_changed"] is False
    assert adaptive["reranked_file_order"] == relevance_order
    assert shadow["role_aware_file_order"][:2] == ["entry.py", "changed.py"]
    assert shadow["metrics"]["recall@3"] == 1.0
    assert "noise" in shadow["excluded_predicted_incidental"]
    changed = next(
        row for row in shadow["candidates"] if row["candidate"] == "changed_handler"
    )
    assert changed["coherent_repair_role"] == "implementation_target"
    assert changed["eligible"] is True


def test_v1o_role_question_and_policy_are_independent_of_historical_gold():
    first_provider = TwoPassProvider()
    first = run_graph_task_v1o(
        _context(), _task("changed.py"), _retrieval(), _adaptive(), first_provider
    )
    second_provider = TwoPassProvider()
    second = run_graph_task_v1o(
        _context(), _task("noise.py"), _retrieval(), _adaptive(), second_provider
    )
    assert (
        first["adaptive"]["role_shadow"]["role_aware_candidate_order"]
        == second["adaptive"]["role_shadow"]["role_aware_candidate_order"]
    )
    baseline = baseline_rank(
        first_provider.calls[1][0]["grounded_context"]["candidates"]
    )
    for index, item in enumerate(baseline):
        assert first_provider.calls[1][1]["role_%d" % index].instructions == (
            ROLE_PROMPT % item.candidate_id
        )
