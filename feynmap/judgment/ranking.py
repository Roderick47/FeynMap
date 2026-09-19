"""Task-aware reranking over FeynMap-grounded candidates.

Context Ranker v1 deliberately leaves canonical graph truth untouched. It only
reorders candidates that deterministic FeynMap retrieval has already selected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .contracts import JudgmentProvider, JudgmentQuestion


@dataclass(frozen=True)
class RankedCandidate:
    candidate: Mapping[str, Any]
    baseline_rank: int
    judgment_probability: Optional[float] = None

    @property
    def candidate_id(self) -> str:
        return str(self.candidate["id"])

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "candidate": dict(self.candidate),
            "baseline_rank": self.baseline_rank,
        }
        if self.judgment_probability is not None:
            payload["judgment_probability"] = float(self.judgment_probability)
        return payload


def baseline_rank(candidates: Sequence[Mapping[str, Any]]) -> List[RankedCandidate]:
    """Preserve deterministic FeynMap candidate order as the benchmark baseline."""
    ranked: List[RankedCandidate] = []
    seen = set()
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, Mapping) or not candidate.get("id"):
            raise ValueError("each candidate must be a mapping with a non-empty id")
        candidate_id = str(candidate["id"])
        if candidate_id in seen:
            raise ValueError("candidate ids must be unique")
        seen.add(candidate_id)
        ranked.append(RankedCandidate(dict(candidate), index))
    return ranked


def rerank_with_judgments(
    task: Any,
    candidates: Sequence[Mapping[str, Any]],
    provider: JudgmentProvider,
    *,
    shared_state: Optional[Mapping[str, Any]] = None,
) -> List[RankedCandidate]:
    """Rerank deterministic candidates by independent relevance judgments.

    The provider receives all candidates as shared context, while each question
    asks about one candidate. Ties preserve deterministic baseline order.
    """
    baseline = baseline_rank(candidates)
    if not baseline:
        return []

    state: Dict[str, Any] = {
        "task": task if isinstance(task, Mapping) else {"description": str(task)},
        "candidates": [dict(item.candidate) for item in baseline],
    }
    if shared_state:
        state["grounded_context"] = dict(shared_state)

    questions = {}
    key_to_id = {}
    for index, item in enumerate(baseline):
        key = "candidate_%d" % index
        key_to_id[key] = item.candidate_id
        questions[key] = JudgmentQuestion.noul(
            "Given task and grounded context, is candidate id %r relevant to completing the task? "
            "Judge only relevance; do not reinterpret graph evidence confidence." % item.candidate_id
        )

    result = provider.evaluate(state, questions)
    probabilities: Dict[str, float] = {}
    for key, candidate_id in key_to_id.items():
        answer = result.answers[key]
        probability = float(answer.value)
        probabilities[candidate_id] = max(0.0, min(1.0, probability))

    ranked = [
        RankedCandidate(
            item.candidate,
            item.baseline_rank,
            probabilities[item.candidate_id],
        )
        for item in baseline
    ]
    ranked.sort(
        key=lambda item: (
            -float(item.judgment_probability or 0.0),
            item.baseline_rank,
            item.candidate_id,
        )
    )
    return ranked
