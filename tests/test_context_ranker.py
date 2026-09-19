from types import SimpleNamespace

import pytest

from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.benchmark import run_benchmark, validate_dataset
from feynmap.judgment.ranking import baseline_rank, rerank_with_judgments


class FakeProvider:
    name = "fake"

    def __init__(self, probabilities):
        self.probabilities = probabilities
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        candidates = state["candidates"]
        answers = {}
        for index, candidate in enumerate(candidates):
            answers["candidate_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL,
                self.probabilities[candidate["id"]],
            )
        return JudgmentResult("fake", "fake-v1", answers)


def dataset():
    return {
        "schema": "feynmap.context_ranker_benchmark.v1",
        "name": "unit",
        "tasks": [
            {
                "id": "t1",
                "description": "fix target",
                "candidates": [
                    {"id": "noise", "summary": "unrelated"},
                    {"id": "target", "summary": "relevant"},
                    {"id": "helper", "summary": "also relevant"},
                ],
                "relevant": ["target", "helper"],
                "essential": ["target"],
            }
        ],
    }


def test_baseline_preserves_deterministic_order():
    ranked = baseline_rank([{"id": "b"}, {"id": "a"}])
    assert [item.candidate_id for item in ranked] == ["b", "a"]
    assert [item.baseline_rank for item in ranked] == [1, 2]


def test_judgment_reranker_moves_relevant_candidate_without_mutating_candidates():
    candidates = [{"id": "noise"}, {"id": "target"}, {"id": "helper"}]
    provider = FakeProvider({"noise": 0.05, "target": 0.95, "helper": 0.7})
    ranked = rerank_with_judgments("fix target", candidates, provider)
    assert [item.candidate_id for item in ranked] == ["target", "helper", "noise"]
    assert candidates == [{"id": "noise"}, {"id": "target"}, {"id": "helper"}]
    assert provider.calls[0][0]["task"]["description"] == "fix target"


def test_benchmark_compares_baseline_and_reranked_metrics():
    provider = FakeProvider({"noise": 0.05, "target": 0.95, "helper": 0.7})
    result = run_benchmark(dataset(), provider, ks=(1, 2))
    assert result["baseline"]["essential_recall@1"] == pytest.approx(0.0)
    assert result["reranked"]["essential_recall@1"] == pytest.approx(1.0)
    assert result["baseline"]["relevant_recall@2"] == pytest.approx(0.5)
    assert result["reranked"]["relevant_recall@2"] == pytest.approx(1.0)


def test_dataset_rejects_unlabeled_or_inconsistent_ids():
    broken = dataset()
    broken["tasks"][0]["essential"] = ["missing"]
    with pytest.raises(ValueError):
        validate_dataset(broken)
