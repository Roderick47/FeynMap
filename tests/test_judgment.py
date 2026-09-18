from types import SimpleNamespace

import pytest

from feynmap.judgment import (
    JevJudgmentProvider,
    JudgmentKind,
    JudgmentProviderError,
    JudgmentQuestion,
    build_judgment_state,
)


def test_question_contracts_validate_and_serialize():
    question = JudgmentQuestion.choice(
        "Which candidate matters most?",
        {"A": "first candidate", "B": "second candidate"},
    )
    assert question.kind == JudgmentKind.CHOICE
    assert question.to_wire() == {
        "type": "choice",
        "instructions": "Which candidate matters most?",
        "criteria": {"A": "first candidate", "B": "second candidate"},
    }

    with pytest.raises(ValueError):
        JudgmentQuestion.choice("Pick one", {})
    with pytest.raises(ValueError):
        JudgmentQuestion.score("Rate it", [])
    with pytest.raises(ValueError):
        JudgmentQuestion.noul("Is it true?", {"maybe": "unclear"})


def test_state_builder_preserves_evidence_semantics_without_probability_conversion():
    context = {
        "snapshot": {"snapshot_id": "s1", "revision": "abc"},
        "root": {
            "id": "root",
            "name": "root",
            "kind": "function",
            "confidence": 0.8,
            "confidence_tier": "supported",
        },
        "nodes": [
            {
                "id": "candidate",
                "name": "candidate",
                "kind": "function",
                "confidence": 0.7,
                "confidence_tier": "inferred",
            }
        ],
        "relationships": [
            {
                "source": "root",
                "relationship": "calls",
                "target": "candidate",
                "confidence": 0.8,
                "confidence_tier": "supported",
            }
        ],
        "grounding": {"unknown": "absence is not proof of impossibility"},
        "budget": {
            "omitted_nodes": 3,
            "omitted_relationships": 5,
            "truncated": True,
            "estimated_tokens": 900,
        },
    }

    state = build_judgment_state("Find the likely fault path", context)
    assert state["root"]["confidence_tier"] == "supported"
    assert state["candidates"][0]["confidence_tier"] == "inferred"
    assert state["relationships"][0]["confidence_tier"] == "supported"
    assert state["omissions"]["truncated"] is True
    assert "probability" not in state["root"]
    assert "judgment_probability" not in state["root"]


class FakeJevClient:
    def __init__(self):
        self.calls = []

    def system_one(self, *, state, questions, model):
        self.calls.append({"state": state, "questions": questions, "model": model})
        return SimpleNamespace(
            model="jev-1.13.0",
            request_id="req_test",
            usage=SimpleNamespace(input_tokens=321, output_tokens=0),
            answers={
                "relevant": SimpleNamespace(type="noul", noul=0.91),
                "candidate": SimpleNamespace(
                    type="choice",
                    choice="C2",
                    probabilities={"C1": 0.1, "C2": 0.8, "none": 0.1},
                    confidence=0.7,
                ),
                "risk": SimpleNamespace(
                    type="score",
                    score=1.6,
                    probabilities={0: 0.05, 1: 0.3, 2: 0.6, 3: 0.05},
                    confidence=0.55,
                    legend={0: "none", 1: "local", 2: "subsystem", 3: "system-wide"},
                ),
            },
        )


def test_jev_provider_normalizes_typed_answers_and_pins_model():
    client = FakeJevClient()
    provider = JevJudgmentProvider(client=client)
    questions = {
        "relevant": JudgmentQuestion.noul("Is the candidate set relevant to the task?"),
        "candidate": JudgmentQuestion.choice(
            "Which candidate is most relevant to the task?",
            {"C1": None, "C2": None, "none": "No candidate is relevant."},
        ),
        "risk": JudgmentQuestion.score(
            "How broad is the likely change impact?",
            ["none", "local", "subsystem", "system-wide"],
        ),
    }

    result = provider.evaluate({"task": {"description": "fix bug"}, "candidates": []}, questions)

    assert client.calls[0]["model"] == "jev-1.13.0"
    assert client.calls[0]["questions"]["relevant"]["type"] == "noul"
    assert result.provider == "jev"
    assert result.model == "jev-1.13.0"
    assert result.request_id == "req_test"
    assert result.usage == {"input_tokens": 321, "output_tokens": 0}
    assert result.answers["relevant"].value == pytest.approx(0.91)
    assert result.answers["relevant"].confidence is None
    assert result.answers["candidate"].value == "C2"
    assert result.answers["candidate"].probabilities["C2"] == pytest.approx(0.8)
    assert result.answers["candidate"].confidence == pytest.approx(0.7)
    assert result.answers["risk"].value == pytest.approx(1.6)
    assert result.answers["risk"].legend["2"] == "subsystem"


def test_jev_provider_rejects_partial_responses():
    class PartialClient:
        def system_one(self, *, state, questions, model):
            return SimpleNamespace(model=model, usage=None, answers={})

    provider = JevJudgmentProvider(client=PartialClient())
    with pytest.raises(JudgmentProviderError, match="omitted answers"):
        provider.evaluate({}, {"relevant": JudgmentQuestion.noul("Is this relevant?")})
