import json
from pathlib import Path

import pytest

from feynmap.judgment.ai_repair_benchmark import _contains_leakage_key
from feynmap.judgment.ai_repair_context import (
    CONTEXT_SCHEMA,
    generate_context,
)
from feynmap.judgment.contracts import (
    JudgmentAnswer,
    JudgmentKind,
    JudgmentProvider,
    JudgmentResult,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "experiments" / "ai_repair_r1_fixture.json"


class FakeProvider(JudgmentProvider):
    @property
    def name(self):
        return "fake"

    def evaluate(self, state, questions):
        answers = {}
        for key, question in questions.items():
            index = int(key.rsplit("_", 1)[1])
            if question.kind == JudgmentKind.NOUL:
                answers[key] = JudgmentAnswer(
                    JudgmentKind.NOUL,
                    max(0.05, 0.95 - index * 0.03),
                )
                continue
            role = (
                "implementation_target"
                if index == 0
                else "supporting_context"
                if index == 1
                else "structural_bridge"
                if index == 2
                else "incidental_context"
            )
            probabilities = {
                "implementation_target": 0.05,
                "structural_bridge": 0.05,
                "supporting_context": 0.05,
                "incidental_context": 0.05,
            }
            probabilities[role] = 0.85
            answers[key] = JudgmentAnswer(
                JudgmentKind.CHOICE,
                role,
                probabilities=probabilities,
            )
        return JudgmentResult(
            provider="fake",
            model="fake-r1",
            answers=answers,
            request_id="fake-request",
            usage={"input_tokens": 10, "output_tokens": 2},
        )


def _spec():
    with SPEC_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ids(context):
    return [str(row["id"]) for row in context["candidates"]]


def test_deterministic_context_is_repeatable_and_excludes_sealed_oracles():
    spec = _spec()
    first = generate_context(
        spec,
        "bounded-retry-delay",
        "deterministic_context",
        project_root=REPO_ROOT,
    )
    second = generate_context(
        spec,
        "bounded-retry-delay",
        "deterministic_context",
        project_root=REPO_ROOT,
    )

    assert first["schema"] == CONTEXT_SCHEMA
    assert first == second
    assert first["analysis_snapshot"]["snapshot_id"] == second["analysis_snapshot"]["snapshot_id"]
    assert first["generation"]["judgment_provider_used"] is False
    assert _contains_leakage_key(first) is None

    rendered = json.dumps(first, sort_keys=True)
    assert "verify.py" not in rendered
    assert "required_tests" not in rendered
    assert "acceptable_change_sets" not in rendered
    assert any(
        (row.get("location") or {}).get("path") == "backoff.py"
        for row in first["candidates"]
    )


def test_relevance_context_reranks_same_bounded_candidate_pool():
    spec = _spec()
    provider = FakeProvider()
    deterministic = generate_context(
        spec,
        "case-insensitive-header-override",
        "deterministic_context",
        project_root=REPO_ROOT,
    )
    relevance = generate_context(
        spec,
        "case-insensitive-header-override",
        "relevance_context",
        project_root=REPO_ROOT,
        provider=provider,
    )

    assert set(_ids(relevance)) == set(_ids(deterministic))
    assert relevance["relationships"] == deterministic["relationships"]
    assert relevance["generation"]["context_order_owner"] == "semantic_relevance"
    assert all(
        "semantic_relevance_probability" in row
        for row in relevance["candidates"]
    )
    assert _contains_leakage_key(relevance) is None


def test_dual_channel_preserves_relevance_context_order_and_candidate_retention():
    spec = _spec()
    provider = FakeProvider()
    relevance = generate_context(
        spec,
        "idempotent-reservation-release",
        "relevance_context",
        project_root=REPO_ROOT,
        provider=provider,
    )
    dual = generate_context(
        spec,
        "idempotent-reservation-release",
        "dual_channel",
        project_root=REPO_ROOT,
        provider=provider,
    )

    assert _ids(dual) == _ids(relevance)
    assert dual["relationships"] == relevance["relationships"]
    guidance = dual["repair_guidance"]
    assert guidance["context_order_changed_by_roles"] is False
    assert guidance["candidate_retention_ratio"] == 1.0
    assert set(guidance["edit_target_candidate_order"]) == set(_ids(dual))
    assert set(guidance["role_lanes"]) == {
        "implementation_target",
        "structural_bridge",
        "supporting_context",
        "incidental_context",
    }
    assert dual["generation"]["roles"]["policy"] == "non_destructive_dual_channel_v1q"
    assert _contains_leakage_key(dual) is None


def test_relevance_and_dual_context_require_explicit_judgment_provider():
    spec = _spec()
    with pytest.raises(ValueError, match="requires an explicit judgment provider"):
        generate_context(
            spec,
            "bounded-retry-delay",
            "relevance_context",
            project_root=REPO_ROOT,
        )
    with pytest.raises(ValueError, match="requires an explicit judgment provider"):
        generate_context(
            spec,
            "bounded-retry-delay",
            "dual_channel",
            project_root=REPO_ROOT,
        )
