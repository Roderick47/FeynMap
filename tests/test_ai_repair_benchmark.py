import copy
import json
from pathlib import Path

import pytest

from feynmap.judgment.ai_repair_benchmark import (
    AGENT_INPUT_SCHEMA,
    ARMS,
    BENCHMARK_SCHEMA,
    COMPARISON_SCHEMA,
    build_agent_input,
    compare_manifests,
    content_hash,
    create_run_manifest,
    load_json,
    score_manifest,
    validate_manifest,
    validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "experiments" / "ai_repair_r1_fixture.json"


def _spec():
    return load_json(SPEC_PATH)


def _context():
    return {
        "schema": "feynmap.context_fixture.v1",
        "snapshot_id": "snapshot-1",
        "candidates": [{"id": "symbol:backoff", "path": "backoff.py"}],
    }


def _outcome(*, changed_files=None, passed=True, extra=None):
    value = {
        "patch_produced": True,
        "patch_sha256": "a" * 64,
        "changed_files": changed_files or ["backoff.py"],
        "tests": [
            {
                "id": "bounded-retry-delay-check",
                "status": "passed" if passed else "failed",
            }
        ],
        "first_proposed_edit": {"path": "backoff.py", "start_line": 1},
        "unsupported_claims": [],
        "repository_searches": 2,
        "extra_context_requests": 1,
        "elapsed_seconds": 12.5,
        "usage": {"input_tokens": 100, "output_tokens": 40},
    }
    value.update(extra or {})
    return value


def _manifest(arm="unassisted", attempt=1, outcome=None):
    spec = _spec()
    context = None if arm == "unassisted" else _context()
    agent_input = build_agent_input(spec, "bounded-retry-delay", arm, context)
    return create_run_manifest(
        spec,
        agent_input,
        attempt=attempt,
        agent={"provider": "fixture-agent", "model": "fixture-v1"},
        outcome=outcome or _outcome(),
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:13+00:00",
    )


def test_fixture_spec_is_valid_and_independent_from_wikonomi():
    spec = _spec()
    validate_spec(spec)

    assert spec["schema"] == BENCHMARK_SCHEMA
    assert spec["evaluation_tier"] == "development_fixture"
    assert tuple(spec["arms"]) == ARMS
    assert len(spec["tasks"]) == 3
    assert "wikonomi" not in json.dumps(spec).lower()
    for task in spec["tasks"]:
        locator = task["repository"]["locator"]
        fixture = ROOT / locator.split("fixture:", 1)[1]
        assert fixture.is_dir()
        assert (fixture / "verify.py").is_file()


def test_agent_input_excludes_oracle_and_requires_context_by_arm():
    spec = _spec()
    payload = build_agent_input(spec, "bounded-retry-delay", "dual_channel", _context())

    assert payload["schema"] == AGENT_INPUT_SCHEMA
    assert payload["benchmark_hash"] == content_hash(spec)
    assert "oracle" not in json.dumps(payload).lower()
    assert payload["task"]["description"] == spec["tasks"][0]["description"]
    with pytest.raises(ValueError, match="assisted arms require"):
        build_agent_input(spec, "bounded-retry-delay", "dual_channel")
    with pytest.raises(ValueError, match="unassisted arm"):
        build_agent_input(spec, "bounded-retry-delay", "unassisted", _context())


def test_agent_context_rejects_structural_oracle_leakage():
    context = _context()
    context["oracle"] = {"required_changed_files": ["backoff.py"]}
    with pytest.raises(ValueError, match="reserved oracle key"):
        build_agent_input(
            _spec(), "bounded-retry-delay", "deterministic_context", context
        )


def test_run_manifest_is_content_addressed_and_tamper_evident():
    manifest = _manifest()
    validate_manifest(_spec(), manifest)
    assert manifest == _manifest()

    changed = copy.deepcopy(manifest)
    changed["outcome"]["elapsed_seconds"] = 13.0
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_manifest(_spec(), changed)


def test_scoring_uses_hidden_tests_and_best_change_set():
    score = score_manifest(_spec(), _manifest())

    assert score["oracle_passed"] is True
    assert score["strict_success"] is True
    assert score["required_test_pass_rate"] == 1.0
    assert score["required_file_recall"] == 1.0
    assert score["allowed_file_precision"] == 1.0
    assert score["first_edit_allowed"] is True


def test_scoring_reports_unnecessary_and_forbidden_changes():
    outcome = _outcome(changed_files=["backoff.py", "verify.py"])
    score = score_manifest(_spec(), _manifest(outcome=outcome))

    assert score["oracle_passed"] is False
    assert score["strict_success"] is False
    assert score["forbidden_changed_files"] == ["verify.py"]
    assert score["unnecessary_changed_files"] == ["verify.py"]
    assert score["allowed_file_precision"] == 0.5


def test_comparison_reports_arm_deltas_and_incomplete_matrix():
    baseline = _manifest("unassisted", outcome=_outcome(passed=False))
    assisted = _manifest("dual_channel", outcome=_outcome())
    result = compare_manifests(_spec(), [baseline, assisted])

    assert result["schema"] == COMPARISON_SCHEMA
    assert result["complete_task_arm_matrix"] is False
    assert result["arms"]["unassisted"]["oracle_passed"] == 0.0
    assert result["arms"]["dual_channel"]["oracle_passed"] == 1.0
    assert result["deltas_from_unassisted"]["dual_channel"]["oracle_passed"] == 1.0
    assert result["missing_task_arms"]


def test_comparison_rejects_duplicate_task_arm_attempt():
    manifest = _manifest()
    with pytest.raises(ValueError, match="repeats a task/arm/attempt"):
        compare_manifests(_spec(), [manifest, manifest])
