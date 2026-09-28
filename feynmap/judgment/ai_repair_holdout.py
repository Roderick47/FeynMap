"""Admission and freeze gate for R1 held-out repair corpora.

The benchmark harness already content-addresses run manifests. This module adds
one earlier scientific checkpoint: freeze the held-out corpus itself before any
assisted-arm result is observed.

It does not select tasks or run agents. It validates benchmark-level holdout
metadata, rejects known development/historical task reuse, and emits a compact
content-addressed lock artifact that can be checked before every R1 run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Tuple

from .ai_repair_benchmark import (
    ARMS,
    BENCHMARK_SCHEMA,
    content_hash,
    load_json,
    validate_spec,
)

HOLDOUT_LOCK_SCHEMA = "feynmap.ai_repair_holdout_lock.v1"
MIN_HELD_OUT_TASKS = 5

# Frozen experiments that must not silently become the R1 held-out corpus.
KNOWN_EXCLUDED_TASK_IDS = {
    "bounded-retry-delay",
    "case-insensitive-header-override",
    "idempotent-reservation-release",
    "wikonomi-map-first-home",
    "wikonomi-map-history",
    "wikonomi-location-first",
    "wikonomi-price-accuracy",
    "wikonomi-guide-formatting",
}


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("%s must be non-empty" % label)
    return text


def _selection_metadata(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    value = spec.get("holdout")
    if not isinstance(value, Mapping):
        raise ValueError("held-out benchmark requires a holdout metadata object")
    return value


def validate_holdout_spec(
    spec: Mapping[str, Any],
    *,
    minimum_tasks: int = MIN_HELD_OUT_TASKS,
) -> None:
    """Apply R1-specific admission checks without changing base benchmark schema."""
    validate_spec(spec)
    if spec.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("unsupported repair benchmark schema")
    if spec.get("evaluation_tier") != "held_out":
        raise ValueError("R1 corpus freeze requires evaluation_tier=held_out")
    if tuple(spec.get("arms") or ()) != ARMS:
        raise ValueError("R1 held-out corpus must retain the frozen arm order")

    tasks = list(spec.get("tasks") or [])
    if len(tasks) < max(1, int(minimum_tasks)):
        raise ValueError(
            "R1 held-out corpus requires at least %d tasks" % int(minimum_tasks)
        )

    metadata = _selection_metadata(spec)
    _nonempty(metadata.get("corpus_id"), "holdout.corpus_id")
    _nonempty(metadata.get("selection_policy"), "holdout.selection_policy")
    _nonempty(metadata.get("selected_at"), "holdout.selected_at")
    _nonempty(metadata.get("selection_owner"), "holdout.selection_owner")

    if metadata.get("assisted_results_observed_before_freeze") is not False:
        raise ValueError(
            "holdout.assisted_results_observed_before_freeze must be false"
        )
    if metadata.get("policy_tuning_allowed_after_freeze") is not False:
        raise ValueError("holdout.policy_tuning_allowed_after_freeze must be false")

    task_ids: Set[str] = set()
    identities: Set[Tuple[str, str, str]] = set()
    source_groups: Set[str] = set()
    for task in tasks:
        task_id = _nonempty(task.get("id"), "task.id")
        if task_id in KNOWN_EXCLUDED_TASK_IDS:
            raise ValueError(
                "held-out task reuses an excluded development/historical id: %s"
                % task_id
            )
        if task_id in task_ids:
            raise ValueError("duplicate held-out task id: %s" % task_id)
        task_ids.add(task_id)

        repository = task["repository"]
        identity = (
            str(repository["locator"]),
            str(repository["revision"]),
            str(repository["content_hash"]),
        )
        if identity in identities:
            raise ValueError(
                "held-out tasks must not duplicate the same repository snapshot: %s"
                % task_id
            )
        identities.add(identity)

        admission = task.get("admission")
        if not isinstance(admission, Mapping):
            raise ValueError("held-out task %s requires admission metadata" % task_id)
        _nonempty(admission.get("source_group"), "task.admission.source_group")
        _nonempty(admission.get("source_reference"), "task.admission.source_reference")
        _nonempty(admission.get("selection_reason"), "task.admission.selection_reason")
        if admission.get("used_for_policy_tuning") is not False:
            raise ValueError(
                "task %s admission.used_for_policy_tuning must be false" % task_id
            )
        if admission.get("solution_inspected_before_selection") is not False:
            raise ValueError(
                "task %s admission.solution_inspected_before_selection must be false"
                % task_id
            )
        source_groups.add(str(admission["source_group"]))

    # Do not force multi-repository diversity, but record when all tasks come from
    # one source group. The lock makes that limitation visible to later reports.
    if not source_groups:
        raise ValueError("held-out corpus has no source groups")


def build_holdout_lock(
    spec: Mapping[str, Any],
    *,
    minimum_tasks: int = MIN_HELD_OUT_TASKS,
) -> Dict[str, Any]:
    validate_holdout_spec(spec, minimum_tasks=minimum_tasks)
    metadata = _selection_metadata(spec)
    tasks = []
    source_groups = set()
    for task in spec["tasks"]:
        repository = task["repository"]
        admission = task["admission"]
        source_groups.add(str(admission["source_group"]))
        tasks.append(
            {
                "id": str(task["id"]),
                "description_hash": content_hash(str(task["description"])),
                "repository": {
                    "locator": str(repository["locator"]),
                    "revision": str(repository["revision"]),
                    "content_hash_policy": str(repository["content_hash_policy"]),
                    "content_hash": str(repository["content_hash"]),
                },
                "oracle_hash": content_hash(task["oracle"]),
                "admission_hash": content_hash(admission),
            }
        )

    payload = {
        "schema": HOLDOUT_LOCK_SCHEMA,
        "benchmark_schema": str(spec["schema"]),
        "benchmark_hash": content_hash(spec),
        "corpus_id": str(metadata["corpus_id"]),
        "selected_at": str(metadata["selected_at"]),
        "selection_owner": str(metadata["selection_owner"]),
        "selection_policy_hash": content_hash(str(metadata["selection_policy"])),
        "task_count": len(tasks),
        "source_group_count": len(source_groups),
        "source_groups": sorted(source_groups),
        "arms": list(ARMS),
        "policy": {
            "assisted_results_observed_before_freeze": False,
            "policy_tuning_allowed_after_freeze": False,
            "excluded_known_task_ids": sorted(KNOWN_EXCLUDED_TASK_IDS),
        },
        "tasks": sorted(tasks, key=lambda row: row["id"]),
    }
    payload["lock_id"] = content_hash(payload)
    return payload


def validate_holdout_lock(
    spec: Mapping[str, Any],
    lock: Mapping[str, Any],
    *,
    minimum_tasks: int = MIN_HELD_OUT_TASKS,
) -> None:
    expected = build_holdout_lock(spec, minimum_tasks=minimum_tasks)
    if lock != expected:
        raise ValueError("held-out corpus lock does not match the benchmark spec")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and freeze an R1 held-out repair corpus"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("spec")
    freeze.add_argument("--minimum-tasks", type=int, default=MIN_HELD_OUT_TASKS)
    freeze.add_argument("--pretty", action="store_true")

    check = subparsers.add_parser("check")
    check.add_argument("spec")
    check.add_argument("lock")
    check.add_argument("--minimum-tasks", type=int, default=MIN_HELD_OUT_TASKS)
    check.add_argument("--pretty", action="store_true")

    args = parser.parse_args(argv)
    spec = load_json(Path(args.spec))
    if args.command == "freeze":
        result = build_holdout_lock(spec, minimum_tasks=args.minimum_tasks)
    else:
        lock = load_json(Path(args.lock))
        validate_holdout_lock(spec, lock, minimum_tasks=args.minimum_tasks)
        result = {
            "schema": HOLDOUT_LOCK_SCHEMA,
            "status": "valid",
            "benchmark_hash": content_hash(spec),
            "lock_id": str(lock["lock_id"]),
        }

    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
