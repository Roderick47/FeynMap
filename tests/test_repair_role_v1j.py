import json
from pathlib import Path

import pytest

from feynmap.judgment import JudgmentAnswer, JudgmentKind, JudgmentResult
from feynmap.judgment.repair_role_v1j import (
    REPAIR_ROLES,
    V1J_SCHEMA,
    build_questions,
    build_task_state,
    run_experiment,
    validate_spec,
)


SPEC = Path(__file__).parents[1] / "experiments" / "repair_role_v1j.json"


def _spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


class FixtureOracleProvider:
    name = "fixture-oracle"

    def __init__(self, spec):
        self.labels = {
            str(candidate["id"]): dict(candidate["gold"])
            for task in spec["tasks"]
            for candidate in task["candidates"]
        }
        self.states = []
        self.questions = []

    def evaluate(self, state, questions):
        self.states.append(state)
        self.questions.append(questions)
        answers = {}
        for index, candidate in enumerate(state["grounded_context"]["candidates"]):
            gold = self.labels[str(candidate["id"])]
            role = str(gold["repair_role"])
            answers["relevance_%d" % index] = JudgmentAnswer(
                JudgmentKind.NOUL,
                0.95 if gold["semantic_relevance"] else 0.05,
            )
            answers["role_%d" % index] = JudgmentAnswer(
                JudgmentKind.CHOICE,
                role,
                probabilities={
                    item: 0.97 if item == role else 0.01 for item in REPAIR_ROLES
                },
                confidence=0.96,
            )
        return JudgmentResult(
            provider=self.name,
            model="fixture-v1",
            answers=answers,
            request_id="fixture-request",
            usage={"input_tokens": 100, "output_tokens": 20},
        )


def test_v1j_fixture_is_independent_balanced_and_region_labeled():
    spec = _spec()
    validate_spec(spec)
    assert spec["schema"] == V1J_SCHEMA
    assert len(spec["tasks"]) == 4
    for task in spec["tasks"]:
        assert {item["gold"]["repair_role"] for item in task["candidates"]} == set(
            REPAIR_ROLES
        )
        assert all(item["region"]["start_line"] > 0 for item in task["candidates"])
        assert "wikonomi" not in json.dumps(task).casefold()


def test_v1j_provider_state_and_questions_do_not_expose_gold_labels():
    task = _spec()["tasks"][0]
    state = build_task_state(task)
    questions = build_questions(task)
    assert "gold" not in json.dumps(state).casefold()
    assert len(questions) == 2 * len(task["candidates"])
    assert questions["relevance_0"].kind == JudgmentKind.NOUL
    assert questions["role_0"].kind == JudgmentKind.CHOICE
    assert set(questions["role_0"].criteria) == set(REPAIR_ROLES)


def test_v1j_scores_relevance_roles_and_implementation_target_ranking():
    spec = _spec()
    provider = FixtureOracleProvider(spec)
    result = run_experiment(spec, provider)
    assert result["status"] == "judged"
    assert result["fixture_summary"]["wikonomi_tasks_used"] is False
    assert result["metrics"]["semantic_relevance_accuracy"] == 1.0
    assert result["metrics"]["repair_role_accuracy"] == 1.0
    assert result["metrics"]["repair_role_macro_f1"] == 1.0
    assert result["target_ranking"]["implementation_target_mrr"] == 1.0
    assert result["target_ranking"]["implementation_target_recall@1"] == 1.0
    assert result["usage"] == {"input_tokens": 400, "output_tokens": 80}
    assert len(provider.states) == 4


def test_v1j_without_provider_validates_fixtures_without_fabricating_scores():
    result = run_experiment(_spec())
    assert result["status"] == "fixture_validated"
    assert result["candidate_count"] == 16
    assert "metrics" not in result


def test_v1j_rejects_missing_role_and_inconsistent_relevance():
    spec = _spec()
    spec["tasks"][0]["candidates"].pop()
    with pytest.raises(ValueError, match="every repair role"):
        validate_spec(spec)

    spec = _spec()
    spec["tasks"][0]["candidates"][0]["gold"]["semantic_relevance"] = False
    with pytest.raises(ValueError, match="inconsistent relevance"):
        validate_spec(spec)
