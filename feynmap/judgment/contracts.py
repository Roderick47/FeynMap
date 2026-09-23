"""Provider-neutral contracts for probabilistic judgments.

Judgments are deliberately separate from FeynMap's evidence confidence. Graph
confidence answers "what evidence supports this fact?" while a judgment answer
expresses a model/provider's probability or bounded decision about supplied
state. Providers must never mutate canonical semantic graph confidence.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence


class JudgmentKind(str, Enum):
    NOUL = "noul"
    CHOICE = "choice"
    SCORE = "score"


class JudgmentProviderError(RuntimeError):
    """A provider failed before producing a complete judgment result."""


@dataclass(frozen=True)
class JudgmentQuestion:
    """One atomic bounded judgment over shared state."""

    kind: JudgmentKind
    instructions: str
    criteria: Optional[Any] = None

    def __post_init__(self) -> None:
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("judgment instructions must be a non-empty string")
        if self.kind == JudgmentKind.CHOICE:
            if not isinstance(self.criteria, Mapping) or not self.criteria:
                raise ValueError("choice judgments require non-empty mapping criteria")
            if any(not isinstance(key, str) or not key for key in self.criteria):
                raise ValueError("choice criteria labels must be non-empty strings")
        elif self.kind == JudgmentKind.SCORE:
            if (
                not isinstance(self.criteria, Sequence)
                or isinstance(self.criteria, (str, bytes))
                or not self.criteria
            ):
                raise ValueError("score judgments require a non-empty ordered criteria sequence")
        elif self.kind == JudgmentKind.NOUL and self.criteria is not None:
            if not isinstance(self.criteria, Mapping):
                raise ValueError("noul criteria must be a mapping when supplied")
            if set(self.criteria) - {"true", "false"}:
                raise ValueError("noul criteria may only define 'true' and 'false'")

    @classmethod
    def noul(cls, instructions: str, criteria: Optional[Mapping[str, Any]] = None) -> "JudgmentQuestion":
        return cls(JudgmentKind.NOUL, instructions, criteria)

    @classmethod
    def choice(cls, instructions: str, criteria: Mapping[str, Any]) -> "JudgmentQuestion":
        return cls(JudgmentKind.CHOICE, instructions, dict(criteria))

    @classmethod
    def score(cls, instructions: str, criteria: Sequence[Any]) -> "JudgmentQuestion":
        return cls(JudgmentKind.SCORE, instructions, list(criteria))

    def to_wire(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "type": self.kind.value,
            "instructions": self.instructions,
        }
        if self.criteria is not None:
            payload["criteria"] = self.criteria
        return payload


@dataclass(frozen=True)
class JudgmentAnswer:
    """Normalized provider response for one question."""

    kind: JudgmentKind
    value: Any
    probabilities: Mapping[str, float] = field(default_factory=dict)
    confidence: Optional[float] = None
    legend: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind.value,
            "value": self.value,
        }
        if self.probabilities:
            payload["probabilities"] = dict(self.probabilities)
        if self.confidence is not None:
            payload["confidence"] = float(self.confidence)
        if self.legend:
            payload["legend"] = dict(self.legend)
        return payload


@dataclass(frozen=True)
class JudgmentResult:
    """Complete answers from a single provider request over shared state."""

    provider: str
    model: Optional[str]
    answers: Mapping[str, JudgmentAnswer]
    request_id: Optional[str] = None
    usage: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "answers": {name: answer.to_dict() for name, answer in self.answers.items()},
            "usage": dict(self.usage),
        }
        if self.request_id:
            payload["request_id"] = self.request_id
        return payload


class JudgmentProvider(ABC):
    """Provider-neutral boundary for bounded probabilistic judgments."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def evaluate(
        self,
        state: Any,
        questions: Mapping[str, JudgmentQuestion],
    ) -> JudgmentResult:
        """Evaluate independent questions against one shared state."""
        raise NotImplementedError
