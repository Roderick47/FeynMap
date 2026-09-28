import copy
import json
from pathlib import Path

import pytest

from feynmap.judgment.ai_repair_holdout import (
    HOLDOUT_LOCK_SCHEMA,
    KNOWN_EXCLUDED_TASK_IDS,
    build_holdout_lock,
    validate_holdout_lock,
    validate_holdout_spec,
)

ROOT = Path(__file__).resolve().parents[1]
DEV_SPEC = ROOT / "experiments" / "ai_repair_r1_fixture.json"


def _dev_spec():
    with DEV_SPEC.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _held_out_spec():
    source = _dev_spec()
    tasks = []
    for index in range(5):
        template = copy.deepcopy(source["tasks"][index % len(source["tasks"])])
        template["id"] = "held-out-%d" % index
        template["repository"]["locator"] = "path:C:/bench/task-%d" % index
        template["repository"]["revision"] = "holdout-rev-%d" % index
        template["repository"]["content_hash"] = ("%064x" % (index + 1))
        template["description"] = "Independent held-out repair task %d." % index
        template["admission"] = {
            "source_group": "group-%d" % (index % 2),
            "source_reference": "reference-%d" % index,
            "selection_reason": "Selected by frozen compatibility criteria.",
            "used_for_policy_tuning": False,
            "solution_inspected_before_selection": False,
        }
        tasks.append(template)
    return {
        "schema": source["schema"],
        "name": "R1 held-out test corpus",
        "evaluation_tier": "held_out",
        "arms": list(source["arms"]),
        "holdout": {
            "corpus_id": "r1-held-out-test",
            "selection_policy": "Select five independent compatible repair tasks before assisted runs.",
            "selected_at": "2026-09-22T00:00:00Z",
            "selection_owner": "test",
            "assisted_results_observed_before_freeze": False,
            "policy_tuning_allowed_after_freeze": False,
        },
        "tasks": tasks,
    }


def test_holdout_lock_is_deterministic_and_content_addressed():
    spec = _held_out_spec()
    first = build_holdout_lock(spec)
    second = build_holdout_lock(copy.deepcopy(spec))

    assert first == second
    assert first["schema"] == HOLDOUT_LOCK_SCHEMA
    assert first["task_count"] == 5
    assert first["source_group_count"] == 2
    assert len(first["lock_id"]) == 64
    validate_holdout_lock(spec, first)


def test_holdout_lock_changes_when_task_text_changes():
    spec = _held_out_spec()
    lock = build_holdout_lock(spec)
    changed = copy.deepcopy(spec)
    changed["tasks"][0]["description"] += " changed"

    with pytest.raises(ValueError, match="does not match"):
        validate_holdout_lock(changed, lock)


def test_known_development_or_historical_task_ids_are_rejected():
    spec = _held_out_spec()
    spec["tasks"][0]["id"] = sorted(KNOWN_EXCLUDED_TASK_IDS)[0]

    with pytest.raises(ValueError, match="excluded development/historical"):
        validate_holdout_spec(spec)


def test_holdout_requires_predeclared_no_tuning_and_no_solution_inspection():
    spec = _held_out_spec()
    spec["holdout"]["policy_tuning_allowed_after_freeze"] = True
    with pytest.raises(ValueError, match="policy_tuning_allowed_after_freeze"):
        validate_holdout_spec(spec)

    spec = _held_out_spec()
    spec["tasks"][1]["admission"]["solution_inspected_before_selection"] = True
    with pytest.raises(ValueError, match="solution_inspected_before_selection"):
        validate_holdout_spec(spec)


def test_holdout_requires_minimum_task_count():
    spec = _held_out_spec()
    spec["tasks"] = spec["tasks"][:4]

    with pytest.raises(ValueError, match="at least 5 tasks"):
        validate_holdout_spec(spec)
