import json
from pathlib import Path

import pytest

from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.repair_role_v1j import REPAIR_ROLES
from feynmap.judgment.repair_role_v1l import (
    V1L_SCHEMA,
    run_experiment,
    validate_spec,
)

SPEC = Path(__file__).parents[1] / "experiments" / "repair_role_v1l.json"


def _spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


class AdjudicationProvider:
    name = "adjudication-oracle"

    def __init__(self, spec, *, choose_alternatives=False):
        self.choose_alternatives = choose_alternatives
        self.labels = {
            (str(task["description"]), str(candidate["id"])): candidate["adjudication"]
            for task in spec["tasks"]
            for candidate in task["candidates"]
        }
        self.states = []

    def evaluate(self, state, questions):
        self.states.append(state)
        description = str(state["task"]["description"])
        answers = {}
        for index, candidate in enumerate(state["grounded_context"]["candidates"]):
            adjudication = self.labels[(description, str(candidate["id"]))]
            labels = adjudication["acceptable_labels"]
            label = labels[-1] if self.choose_alternatives else adjudication["primary"]
            role = str(label["repair_role"])
            answers["relevance_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL,
                0.92 if label["semantic_relevance"] else 0.08,
            )
            answers["role_%d" % index] = JudgmentAnswer(
                JudgmentKind.CHOICE,
                role,
                probabilities={
                    candidate_role: (0.91 if candidate_role == role else 0.03)
                    for candidate_role in REPAIR_ROLES
                },
            )
        return JudgmentResult(
            provider=self.name,
            model="oracle-v1",
            answers=answers,
            usage={"input_tokens": 50, "output_tokens": 10},
        )


def test_v1l_fixture_has_predeclared_ambiguity_without_benchmark_leakage():
    spec = _spec()
    validate_spec(spec)
    assert spec["schema"] == V1L_SCHEMA
    assert len(spec["tasks"]) == 5
    candidates = [
        candidate for task in spec["tasks"] for candidate in task["candidates"]
    ]
    assert len(candidates) == 20
    assert (
        sum(
            len(candidate["adjudication"]["acceptable_labels"]) > 1
            for candidate in candidates
        )
        == 5
    )
    assert all(candidate["adjudication"]["rationale"] for candidate in candidates)
    assert "wikonomi" not in json.dumps(spec).casefold()


def test_v1l_primary_oracle_is_strictly_and_acceptably_correct():
    spec = _spec()
    provider = AdjudicationProvider(spec)
    result = run_experiment(spec, provider)
    assert result["strict_primary_metrics"]["repair_role_accuracy"] == 1.0
    assert result["strict_primary_metrics"]["semantic_relevance_accuracy"] == 1.0
    assert result["acceptable_label_metrics"]["joint_label_acceptance_accuracy"] == 1.0
    assert result["acceptable_label_metrics"]["ambiguous_candidate_count"] == 5
    assert result["target_ranking"]["implementation_target_mrr"] == 1.0
    assert result["unaccepted_cases"] == []
    assert result["usage"] == {"input_tokens": 250, "output_tokens": 50}


def test_v1l_accepts_predeclared_alternatives_without_rewriting_primary_gold():
    spec = _spec()
    result = run_experiment(spec, AdjudicationProvider(spec, choose_alternatives=True))
    assert result["strict_primary_metrics"]["repair_role_accuracy"] == 0.75
    assert result["strict_primary_metrics"]["semantic_relevance_accuracy"] == 0.9
    acceptable = result["acceptable_label_metrics"]
    assert acceptable["repair_role_acceptance_accuracy"] == 1.0
    assert acceptable["semantic_relevance_acceptance_accuracy"] == 1.0
    assert acceptable["joint_label_acceptance_accuracy"] == 1.0
    assert acceptable["ambiguous_joint_acceptance_accuracy"] == 1.0
    assert acceptable["singleton_joint_acceptance_accuracy"] == 1.0
    assert result["unaccepted_cases"] == []


def test_v1l_hides_all_adjudication_metadata_from_provider_state():
    spec = _spec()
    provider = AdjudicationProvider(spec)
    run_experiment(spec, provider)
    serialized = json.dumps(provider.states)
    assert "adjudication" not in serialized
    assert "acceptable_labels" not in serialized
    assert "rationale" not in serialized
    assert "primary" not in serialized


def test_v1l_rejects_ambiguous_implementation_targets():
    spec = _spec()
    adjudication = spec["tasks"][0]["candidates"][0]["adjudication"]
    adjudication["acceptable_labels"].append(
        {"semantic_relevance": True, "repair_role": "supporting_context"}
    )
    with pytest.raises(ValueError, match="implementation-target ambiguity"):
        validate_spec(spec)


def test_v1l_rejects_primary_labels_outside_acceptable_set():
    spec = _spec()
    adjudication = spec["tasks"][0]["candidates"][3]["adjudication"]
    adjudication["acceptable_labels"] = [
        {"semantic_relevance": True, "repair_role": "supporting_context"}
    ]
    with pytest.raises(ValueError, match="primary label must be acceptable"):
        validate_spec(spec)


def test_v1l_without_provider_only_validates_fixture():
    result = run_experiment(_spec())
    assert result["status"] == "fixture_validated"
    assert result["task_count"] == 5
    assert result["candidate_count"] == 20
    assert result["fixture_summary"]["ambiguous_candidate_count"] == 5
    assert result["fixture_summary"]["v1j_prompts_frozen"] is True
    assert "strict_primary_metrics" not in result
