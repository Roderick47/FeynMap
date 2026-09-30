"""Task-conditioned relevance judgments over source-backed behavior.

Source analysis decides what is true.  A relevance judge only decides what
already-grounded evidence is useful for the current task.  This module keeps
those responsibilities separate and makes learned judgment optional.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Tuple

from .behavior import BehaviorKind, BehaviorObservation
from .judgment.contracts import JudgmentProvider, JudgmentQuestion


class RelevanceLabel(str, Enum):
    ESSENTIAL = "essential"
    SUPPORTING = "supporting"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class SufficiencyLabel(str, Enum):
    SUFFICIENT = "sufficient"
    NEEDS_EXPANSION = "needs_expansion"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class TaskEvidenceProfile:
    task: str
    task_type: str
    identifiers: Tuple[str, ...]
    category_weights: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "task_type": self.task_type,
            "identifiers": list(self.identifiers),
            "category_weights": {
                key: round(float(value), 4)
                for key, value in sorted(self.category_weights.items())
            },
        }


@dataclass(frozen=True)
class RelevanceDecision:
    label: RelevanceLabel
    score: float
    reason: str = ""
    probabilities: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "label": self.label.value,
            "score": round(float(self.score), 4),
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.probabilities:
            payload["probabilities"] = {
                key: round(float(value), 4)
                for key, value in sorted(self.probabilities.items())
            }
        return payload


@dataclass(frozen=True)
class SufficiencyDecision:
    label: SufficiencyLabel
    score: float
    reason: str = ""
    missing_dimensions: Tuple[str, ...] = ()

    @property
    def sufficient(self) -> bool:
        return self.label == SufficiencyLabel.SUFFICIENT

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "label": self.label.value,
            "score": round(float(self.score), 4),
            "missing_dimensions": list(self.missing_dimensions),
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def _tokens(value: str) -> Set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    spaced = re.sub(r"[_./:\-]+", " ", spaced)
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9$]+", spaced)
        if len(token) >= 2
    }


def _identifiers(task: str) -> Tuple[str, ...]:
    explicit = set(
        match.group(0)
        for match in re.finditer(
            r"\b(?:[A-Za-z_$][A-Za-z0-9_$]*_[A-Za-z0-9_$]+"
            r"|[a-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*"
            r"|[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]+)+)\b",
            task,
        )
    )
    return tuple(sorted(explicit))


_DEFAULT_WEIGHTS = {
    BehaviorKind.PARAMETER.value: 0.18,
    BehaviorKind.METADATA.value: 0.20,
    BehaviorKind.READ.value: 0.38,
    BehaviorKind.ASSIGNMENT.value: 0.42,
    BehaviorKind.MUTATION.value: 0.68,
    BehaviorKind.CONDITION.value: 0.62,
    BehaviorKind.CALL.value: 0.58,
    BehaviorKind.RETURN.value: 0.62,
    BehaviorKind.RAISE.value: 0.70,
    BehaviorKind.ASSERTION.value: 0.56,
    BehaviorKind.TRANSFORM.value: 0.62,
    BehaviorKind.SIDE_EFFECT.value: 0.72,
    BehaviorKind.MIGRATION.value: 0.68,
}


class RelevanceJudge(ABC):
    """Judge task relevance without changing source/evidence confidence."""

    @abstractmethod
    def profile(self, task: str) -> TaskEvidenceProfile:
        raise NotImplementedError

    @abstractmethod
    def rank(
        self,
        task: str,
        observations: Sequence[BehaviorObservation],
        profile: TaskEvidenceProfile,
    ) -> Mapping[str, RelevanceDecision]:
        raise NotImplementedError

    @abstractmethod
    def sufficiency(
        self,
        task: str,
        observations: Sequence[BehaviorObservation],
        profile: TaskEvidenceProfile,
        *,
        unresolved_identifiers: Sequence[str] = (),
        omitted_relevant: int = 0,
    ) -> SufficiencyDecision:
        raise NotImplementedError


class DeterministicRelevanceJudge(RelevanceJudge):
    """Cheap transparent baseline; learned judges must beat this measurement."""

    def profile(self, task: str) -> TaskEvidenceProfile:
        tokens = _tokens(task)
        weights = dict(_DEFAULT_WEIGHTS)
        task_type = "general_behavior"

        def boost(kinds: Sequence[BehaviorKind], value: float) -> None:
            for kind in kinds:
                weights[kind.value] = max(weights.get(kind.value, 0.0), value)

        if tokens & {"fail", "failure", "error", "exception", "raise", "invalid", "why"}:
            task_type = "failure_behavior"
            boost(
                [BehaviorKind.CONDITION, BehaviorKind.RAISE, BehaviorKind.CALL,
                 BehaviorKind.MUTATION, BehaviorKind.ASSERTION],
                0.82,
            )
        if tokens & {"return", "returns", "result", "output", "produce", "produces"}:
            task_type = "return_behavior"
            boost(
                [BehaviorKind.RETURN, BehaviorKind.CALL, BehaviorKind.CONDITION,
                 BehaviorKind.TRANSFORM],
                0.84,
            )
        if tokens & {"mutate", "mutation", "change", "changes", "quantity", "stock", "write", "update"}:
            task_type = "state_change"
            boost(
                [BehaviorKind.MUTATION, BehaviorKind.ASSIGNMENT, BehaviorKind.CONDITION,
                 BehaviorKind.CALL, BehaviorKind.SIDE_EFFECT],
                0.84,
            )
        if tokens & {"test", "tests", "regression", "assert", "assertion", "expects", "expect"}:
            task_type = "test_behavior"
            boost(
                [BehaviorKind.ASSERTION, BehaviorKind.CALL, BehaviorKind.CONDITION,
                 BehaviorKind.RAISE, BehaviorKind.MUTATION],
                0.86,
            )
        if tokens & {"migration", "migrate", "default", "schema", "field", "priority"}:
            task_type = "migration_behavior"
            boost(
                [BehaviorKind.MIGRATION, BehaviorKind.ASSIGNMENT, BehaviorKind.RETURN,
                 BehaviorKind.CONDITION, BehaviorKind.CALL],
                0.86,
            )
        if tokens & {"normalize", "normalise", "format", "transform", "trim", "uppercase", "lowercase"}:
            task_type = "transformation"
            boost(
                [BehaviorKind.TRANSFORM, BehaviorKind.RETURN, BehaviorKind.CALL,
                 BehaviorKind.CONDITION],
                0.88,
            )
        if tokens & {"side", "effect", "refund", "network", "database", "persist", "save", "send"}:
            task_type = "side_effect"
            boost(
                [BehaviorKind.SIDE_EFFECT, BehaviorKind.CALL, BehaviorKind.MUTATION,
                 BehaviorKind.CONDITION],
                0.88,
            )
        return TaskEvidenceProfile(
            task=task,
            task_type=task_type,
            identifiers=_identifiers(task),
            category_weights=weights,
        )

    def rank(
        self,
        task: str,
        observations: Sequence[BehaviorObservation],
        profile: TaskEvidenceProfile,
    ) -> Mapping[str, RelevanceDecision]:
        task_terms = _tokens(task)
        identifier_terms = set()
        for identifier in profile.identifiers:
            identifier_terms |= _tokens(identifier)
        result: Dict[str, RelevanceDecision] = {}
        for observation in observations:
            evidence_terms = _tokens(
                "%s %s %s %s" % (
                    observation.summary,
                    observation.source,
                    observation.condition or "",
                    observation.symbol_id,
                )
            )
            overlap = len(task_terms & evidence_terms) / float(max(1, len(task_terms)))
            identifier_overlap = bool(identifier_terms & evidence_terms)
            category = float(profile.category_weights.get(observation.kind.value, 0.25))
            score = 0.62 * category + min(0.28, 0.9 * overlap)
            if identifier_overlap:
                score += 0.12
            if observation.condition and observation.kind in {
                BehaviorKind.MUTATION, BehaviorKind.CALL, BehaviorKind.RETURN,
                BehaviorKind.RAISE, BehaviorKind.SIDE_EFFECT,
            }:
                score += 0.06
            score = max(0.0, min(1.0, score))
            if score >= 0.72:
                label = RelevanceLabel.ESSENTIAL
            elif score >= 0.46:
                label = RelevanceLabel.SUPPORTING
            elif score >= 0.28:
                label = RelevanceLabel.UNCERTAIN
            else:
                label = RelevanceLabel.IRRELEVANT
            reason = "category=%.2f overlap=%.2f%s" % (
                category,
                overlap,
                " identifier" if identifier_overlap else "",
            )
            result[observation.id] = RelevanceDecision(label, score, reason)
        return result

    def sufficiency(
        self,
        task: str,
        observations: Sequence[BehaviorObservation],
        profile: TaskEvidenceProfile,
        *,
        unresolved_identifiers: Sequence[str] = (),
        omitted_relevant: int = 0,
    ) -> SufficiencyDecision:
        if unresolved_identifiers:
            return SufficiencyDecision(
                SufficiencyLabel.NEEDS_EXPANSION,
                1.0,
                "explicit requested identifier was not resolved upstream",
                tuple(sorted(set(str(item) for item in unresolved_identifiers))),
            )
        if omitted_relevant:
            return SufficiencyDecision(
                SufficiencyLabel.NEEDS_EXPANSION,
                0.95,
                "relevant grounded observations were omitted by the behavior budget",
                ("behavior_budget",),
            )
        kinds = {item.kind for item in observations}
        if not observations:
            return SufficiencyDecision(
                SufficiencyLabel.NEEDS_EXPANSION,
                0.9,
                "no grounded behavioral observations were delivered",
                ("behavior",),
            )

        required_by_type = {
            "failure_behavior": {BehaviorKind.CONDITION, BehaviorKind.RAISE},
            "return_behavior": {BehaviorKind.RETURN},
            "state_change": {BehaviorKind.MUTATION, BehaviorKind.ASSIGNMENT},
            "test_behavior": {BehaviorKind.ASSERTION},
            "migration_behavior": {BehaviorKind.ASSIGNMENT, BehaviorKind.RETURN, BehaviorKind.CONDITION},
            "transformation": {BehaviorKind.TRANSFORM, BehaviorKind.RETURN},
            "side_effect": {BehaviorKind.CALL, BehaviorKind.SIDE_EFFECT},
        }
        required = required_by_type.get(profile.task_type, set())
        if required and not (required & kinds):
            return SufficiencyDecision(
                SufficiencyLabel.NEEDS_EXPANSION,
                0.8,
                "task-critical behavioral dimension is absent",
                tuple(sorted(kind.value for kind in required)),
            )
        if BehaviorKind.CONDITION in kinds and (
            BehaviorKind.RETURN in kinds
            or BehaviorKind.RAISE in kinds
            or BehaviorKind.MUTATION in kinds
            or BehaviorKind.CALL in kinds
        ):
            return SufficiencyDecision(
                SufficiencyLabel.SUFFICIENT,
                0.8,
                "grounded condition plus consequential behavior is present",
            )
        if required and required & kinds:
            return SufficiencyDecision(
                SufficiencyLabel.SUFFICIENT,
                0.72,
                "task-critical grounded behavior is present",
            )
        if len(kinds) >= 2:
            return SufficiencyDecision(
                SufficiencyLabel.SUFFICIENT,
                0.62,
                "multiple grounded behavioral dimensions are present",
            )
        return SufficiencyDecision(
            SufficiencyLabel.UNCERTAIN,
            0.5,
            "evidence exists but deterministic sufficiency is uncertain",
            ("additional_behavior",),
        )


class JudgmentProviderRelevanceJudge(RelevanceJudge):
    """Optional learned relevance over the same immutable observations.

    A Jev provider works immediately.  Future Laya/Jeff adapters only need to
    implement the existing JudgmentProvider boundary; no P2.4 source or graph
    contract changes are required.
    """

    def __init__(
        self,
        provider: JudgmentProvider,
        *,
        fallback: Optional[DeterministicRelevanceJudge] = None,
    ) -> None:
        self.provider = provider
        self.fallback = fallback or DeterministicRelevanceJudge()

    def profile(self, task: str) -> TaskEvidenceProfile:
        # Keep task typing deterministic for reproducibility; the provider is
        # used where probabilistic judgment is actually valuable: evidence
        # relevance and sufficiency.
        return self.fallback.profile(task)

    def rank(
        self,
        task: str,
        observations: Sequence[BehaviorObservation],
        profile: TaskEvidenceProfile,
    ) -> Mapping[str, RelevanceDecision]:
        if not observations:
            return {}
        state = {
            "task": task,
            "task_profile": profile.to_dict(),
            "observations": [item.to_dict() for item in observations],
            "rule": "Judge relevance only. Do not change whether evidence is source-supported.",
        }
        questions = {
            item.id: JudgmentQuestion.choice(
                "Classify this observation for answering the task. Preserve uncertainty rather than forcing irrelevance.",
                {
                    "essential": "directly needed for the grounded answer",
                    "supporting": "useful corroboration or explanation",
                    "irrelevant": "not useful for this task",
                    "uncertain": "may matter; retain when budget permits",
                },
            )
            for item in observations
        }
        try:
            judged = self.provider.evaluate(state, questions)
        except Exception:
            return self.fallback.rank(task, observations, profile)
        fallback = self.fallback.rank(task, observations, profile)
        result: Dict[str, RelevanceDecision] = {}
        for item in observations:
            answer = judged.answers.get(item.id)
            if answer is None:
                result[item.id] = fallback[item.id]
                continue
            probabilities = {
                str(key).casefold(): float(value)
                for key, value in answer.probabilities.items()
                if str(key).casefold() in {label.value for label in RelevanceLabel}
            }
            raw = str(answer.value).casefold()
            if raw not in {label.value for label in RelevanceLabel} and probabilities:
                raw = max(probabilities, key=probabilities.get)
            try:
                label = RelevanceLabel(raw)
            except ValueError:
                result[item.id] = fallback[item.id]
                continue
            score = probabilities.get(label.value)
            if score is None:
                score = answer.confidence if answer.confidence is not None else fallback[item.id].score
            result[item.id] = RelevanceDecision(
                label=label,
                score=max(0.0, min(1.0, float(score))),
                reason="provider:%s" % judged.provider,
                probabilities=probabilities,
            )
        return result

    def sufficiency(
        self,
        task: str,
        observations: Sequence[BehaviorObservation],
        profile: TaskEvidenceProfile,
        *,
        unresolved_identifiers: Sequence[str] = (),
        omitted_relevant: int = 0,
    ) -> SufficiencyDecision:
        baseline = self.fallback.sufficiency(
            task,
            observations,
            profile,
            unresolved_identifiers=unresolved_identifiers,
            omitted_relevant=omitted_relevant,
        )
        # Deterministic hard failures cannot be overruled by a learned judge.
        if unresolved_identifiers or omitted_relevant:
            return baseline
        state = {
            "task": task,
            "task_profile": profile.to_dict(),
            "observations": [item.to_dict() for item in observations],
            "rule": "Unknown is not false. Request expansion when evidence needed for a grounded answer is absent.",
        }
        question = JudgmentQuestion.choice(
            "Is this grounded evidence set sufficient for a careful answer to the task?",
            {
                "sufficient": "enough evidence is present",
                "needs_expansion": "a material evidence dimension is missing",
                "uncertain": "cannot determine sufficiency safely",
            },
        )
        try:
            judged = self.provider.evaluate(state, {"sufficiency": question})
            answer = judged.answers["sufficiency"]
            probabilities = {str(k).casefold(): float(v) for k, v in answer.probabilities.items()}
            raw = str(answer.value).casefold()
            if raw not in {item.value for item in SufficiencyLabel} and probabilities:
                raw = max(probabilities, key=probabilities.get)
            label = SufficiencyLabel(raw)
            score = probabilities.get(label.value)
            if score is None:
                score = answer.confidence if answer.confidence is not None else baseline.score
            return SufficiencyDecision(
                label,
                max(0.0, min(1.0, float(score))),
                "provider:%s" % judged.provider,
                () if label == SufficiencyLabel.SUFFICIENT else ("provider_requested_expansion",),
            )
        except Exception:
            return baseline
