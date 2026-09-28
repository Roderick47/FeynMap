"""TypeSafe Jev provider for FeynMap judgments.

The provider is optional and imported lazily so FeynMap's dependency-free core
continues to work on Python versions unsupported by the TypeSafe SDK.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .contracts import (
    JudgmentAnswer,
    JudgmentKind,
    JudgmentProvider,
    JudgmentProviderError,
    JudgmentQuestion,
    JudgmentResult,
)


class JevUnavailableError(JudgmentProviderError):
    """The optional TypeSafe SDK is unavailable in this environment."""


class JevJudgmentProvider(JudgmentProvider):
    """Evaluate FeynMap state with TypeSafe Jev using typed bounded questions."""

    DEFAULT_MODEL = "jev-1.13.0"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: Optional[float] = None,
        client: Optional[Any] = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = client

    @property
    def name(self) -> str:
        return "jev"

    def evaluate(
        self,
        state: Any,
        questions: Mapping[str, JudgmentQuestion],
    ) -> JudgmentResult:
        if not questions:
            raise ValueError("at least one judgment question is required")
        for key, question in questions.items():
            if not isinstance(key, str) or not key:
                raise ValueError("judgment question IDs must be non-empty strings")
            if not isinstance(question, JudgmentQuestion):
                raise TypeError("questions must contain JudgmentQuestion values")

        wire_questions = {key: question.to_wire() for key, question in questions.items()}
        response = self._request(state, wire_questions)
        answers = self._normalize_answers(response, questions)
        usage = self._normalize_usage(getattr(response, "usage", None))
        request_id = getattr(response, "request_id", None)
        return JudgmentResult(
            provider=self.name,
            model=getattr(response, "model", self.model),
            answers=answers,
            request_id=str(request_id) if request_id is not None else None,
            usage=usage,
        )

    def _request(self, state: Any, questions: Mapping[str, Dict[str, Any]]) -> Any:
        if self._client is not None:
            return self._client.system_one(state=state, questions=questions, model=self.model)

        try:
            from typesafe_sdk import TypeSafeClient
        except (ImportError, SyntaxError) as exc:
            raise JevUnavailableError(
                "Jev integration requires Python 3.10+ and the optional 'typesafe-sdk' dependency; "
                "install FeynMap with the 'jev' extra."
            ) from exc

        kwargs: Dict[str, Any] = {}
        if self.api_key is not None:
            kwargs["api_key"] = self.api_key
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        with TypeSafeClient(**kwargs) as client:
            return client.system_one(state=state, questions=questions, model=self.model)

    def _normalize_answers(
        self,
        response: Any,
        questions: Mapping[str, JudgmentQuestion],
    ) -> Dict[str, JudgmentAnswer]:
        raw_answers = getattr(response, "answers", None)
        if not isinstance(raw_answers, Mapping):
            raise JudgmentProviderError("Jev response did not contain an answers mapping")

        missing = sorted(set(questions) - set(raw_answers))
        if missing:
            raise JudgmentProviderError("Jev response omitted answers: %s" % ", ".join(missing))

        normalized: Dict[str, JudgmentAnswer] = {}
        for key, question in questions.items():
            answer = raw_answers[key]
            answer_type = getattr(answer, "type", None)
            if answer_type != question.kind.value:
                raise JudgmentProviderError(
                    "Jev answer type mismatch for %s: expected %s, got %s"
                    % (key, question.kind.value, answer_type)
                )

            if question.kind == JudgmentKind.NOUL:
                normalized[key] = JudgmentAnswer(
                    kind=question.kind,
                    value=float(getattr(answer, "noul")),
                )
                continue

            probabilities = {
                str(label): float(probability)
                for label, probability in dict(getattr(answer, "probabilities", {}) or {}).items()
            }
            confidence = getattr(answer, "confidence", None)
            if question.kind == JudgmentKind.CHOICE:
                normalized[key] = JudgmentAnswer(
                    kind=question.kind,
                    value=str(getattr(answer, "choice")),
                    probabilities=probabilities,
                    confidence=float(confidence) if confidence is not None else None,
                )
                continue

            legend = {
                str(level): description
                for level, description in dict(getattr(answer, "legend", {}) or {}).items()
            }
            normalized[key] = JudgmentAnswer(
                kind=question.kind,
                value=float(getattr(answer, "score")),
                probabilities=probabilities,
                confidence=float(confidence) if confidence is not None else None,
                legend=legend,
            )
        return normalized

    @staticmethod
    def _normalize_usage(usage: Any) -> Dict[str, Any]:
        if usage is None:
            return {}
        payload: Dict[str, Any] = {}
        for field in ("input_tokens", "output_tokens"):
            value = getattr(usage, field, None)
            if value is not None:
                payload[field] = int(value)
        return payload
