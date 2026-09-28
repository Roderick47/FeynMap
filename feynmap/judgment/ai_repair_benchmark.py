"""Provider-neutral R1 benchmark contracts for end-to-end AI repair trials.

The harness separates agent-visible task state from hidden evaluation oracles,
creates content-addressed immutable run manifests, scores recorded outcomes,
and compares benchmark arms.  It deliberately does not execute agents, patches,
or test commands; execution adapters can be added without changing the schemas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

BENCHMARK_SCHEMA = "feynmap.ai_repair_benchmark.v1"
AGENT_INPUT_SCHEMA = "feynmap.ai_repair_agent_input.v1"
RUN_SCHEMA = "feynmap.ai_repair_run.v1"
COMPARISON_SCHEMA = "feynmap.ai_repair_comparison.v1"
REPOSITORY_CONTENT_HASH_POLICY = "canonical_text_lf_v1"

ARMS = (
    "unassisted",
    "deterministic_context",
    "relevance_context",
    "dual_channel",
)
TEST_STATUSES = ("passed", "failed", "error", "not_run")
LEAKAGE_KEYS = {
    "acceptable_change_sets",
    "allowed_changed_files",
    "expected_changed_files",
    "forbidden_changed_files",
    "gold",
    "oracle",
    "required_changed_files",
    "required_tests",
    "solution",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Mapping[str, Any]:
    with path.open("rb") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise ValueError("repair benchmark JSON must contain an object")
    return value


def _strings(value: Any, label: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(
            "%s must be a list%s" % (label, "" if allow_empty else " with values")
        )
    result = [str(item) for item in value]
    if any(not item for item in result) or len(result) != len(set(result)):
        raise ValueError("%s values must be non-empty and unique" % label)
    return result


def _task_index(spec: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {str(task["id"]): task for task in spec["tasks"]}


def validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("unsupported AI repair benchmark schema")
    if str(spec.get("evaluation_tier") or "") not in {
        "development_fixture",
        "held_out",
    }:
        raise ValueError("benchmark requires a recognized evaluation tier")
    arms = tuple(_strings(spec.get("arms"), "benchmark arms", allow_empty=False))
    if arms != ARMS:
        raise ValueError("benchmark arms must use the frozen R1 comparison order")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("repair benchmark requires tasks")
    task_ids = [
        str(task.get("id") or "") for task in tasks if isinstance(task, Mapping)
    ]
    if len(task_ids) != len(tasks) or any(not value for value in task_ids):
        raise ValueError("every repair task requires an id")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("repair task ids must be unique")

    for task in tasks:
        task_id = str(task["id"])
        if not str(task.get("description") or "").strip():
            raise ValueError("task %s requires a description" % task_id)
        repository = task.get("repository")
        if not isinstance(repository, Mapping):
            raise ValueError("task %s requires repository identity" % task_id)
        for key in ("locator", "revision", "content_hash", "content_hash_policy"):
            if not str(repository.get(key) or ""):
                raise ValueError("task %s repository requires %s" % (task_id, key))
        if repository["content_hash_policy"] != REPOSITORY_CONTENT_HASH_POLICY:
            raise ValueError(
                "task %s repository content hash policy is unsupported" % task_id
            )
        repository_hash = str(repository["content_hash"])
        if len(repository_hash) != 64:
            raise ValueError("task %s repository content hash is invalid" % task_id)
        try:
            int(repository_hash, 16)
        except ValueError:
            raise ValueError("task %s repository content hash is invalid" % task_id)
        oracle = task.get("oracle")
        if not isinstance(oracle, Mapping):
            raise ValueError("task %s requires a hidden oracle" % task_id)
        tests = oracle.get("required_tests")
        if not isinstance(tests, list) or not tests:
            raise ValueError("task %s requires oracle tests" % task_id)
        test_ids = []
        for test in tests:
            if not isinstance(test, Mapping):
                raise ValueError("task %s has an invalid test oracle" % task_id)
            test_id = str(test.get("id") or "")
            command = test.get("command")
            if (
                not test_id
                or not isinstance(command, list)
                or not command
                or any(not isinstance(value, str) or not value for value in command)
            ):
                raise ValueError(
                    "task %s oracle tests require id and command argv" % task_id
                )
            test_ids.append(test_id)
        if len(test_ids) != len(set(test_ids)):
            raise ValueError("task %s repeats an oracle test id" % task_id)

        change_sets = oracle.get("acceptable_change_sets")
        if not isinstance(change_sets, list) or not change_sets:
            raise ValueError("task %s requires acceptable change sets" % task_id)
        for index, change_set in enumerate(change_sets):
            if not isinstance(change_set, Mapping):
                raise ValueError("task %s has an invalid change set" % task_id)
            required = set(
                _strings(
                    change_set.get("required_files"),
                    "task %s change set %d required files" % (task_id, index),
                    allow_empty=False,
                )
            )
            allowed = set(
                _strings(
                    change_set.get("allowed_files"),
                    "task %s change set %d allowed files" % (task_id, index),
                    allow_empty=False,
                )
            )
            if not required.issubset(allowed):
                raise ValueError("required files must be included in allowed files")
        _strings(
            oracle.get("forbidden_files") or [],
            "task %s forbidden files" % task_id,
        )
        _strings(
            oracle.get("sealed_files") or [],
            "task %s sealed files" % task_id,
        )
        if str(oracle.get("baseline_expectation") or "") not in {
            "at_least_one_failure",
            "all_pass",
        }:
            raise ValueError("task %s requires a baseline expectation" % task_id)


def _contains_leakage_key(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in LEAKAGE_KEYS:
                return normalized
            nested = _contains_leakage_key(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _contains_leakage_key(item)
            if nested:
                return nested
    return None


def build_agent_input(
    spec: Mapping[str, Any],
    task_id: str,
    arm: str,
    context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create the agent-visible payload while excluding every oracle field."""
    validate_spec(spec)
    tasks = _task_index(spec)
    if task_id not in tasks:
        raise ValueError("unknown repair benchmark task: %s" % task_id)
    if arm not in ARMS:
        raise ValueError("unknown repair benchmark arm: %s" % arm)
    if arm == "unassisted" and context is not None:
        raise ValueError("the unassisted arm cannot receive FeynMap context")
    if arm != "unassisted" and not isinstance(context, Mapping):
        raise ValueError("assisted arms require a context object")
    if context is not None:
        leakage = _contains_leakage_key(context)
        if leakage:
            raise ValueError("agent context contains reserved oracle key: %s" % leakage)

    task = tasks[task_id]
    payload = {
        "schema": AGENT_INPUT_SCHEMA,
        "benchmark_hash": content_hash(spec),
        "task": {
            "id": task_id,
            "description": str(task["description"]),
            "repository": deepcopy(dict(task["repository"])),
        },
        "arm": arm,
        "context": deepcopy(dict(context)) if context is not None else None,
    }
    if _contains_leakage_key(payload):
        raise ValueError("agent input leaked benchmark oracle metadata")
    return payload


def validate_agent_input(
    spec: Mapping[str, Any], agent_input: Mapping[str, Any]
) -> None:
    validate_spec(spec)
    if agent_input.get("schema") != AGENT_INPUT_SCHEMA:
        raise ValueError("unsupported AI repair agent input schema")
    if agent_input.get("benchmark_hash") != content_hash(spec):
        raise ValueError("agent input benchmark hash mismatch")
    task = agent_input.get("task") or {}
    task_id = str(task.get("id") or "")
    arm = str(agent_input.get("arm") or "")
    expected = build_agent_input(
        spec,
        task_id,
        arm,
        agent_input.get("context"),
    )
    if agent_input != expected:
        raise ValueError("agent input does not match the benchmark task projection")


def _validate_outcome(outcome: Mapping[str, Any]) -> Dict[str, Any]:
    changed_files = sorted(_strings(outcome.get("changed_files"), "changed files"))
    tests = outcome.get("tests")
    if not isinstance(tests, list):
        raise ValueError("run outcome requires tests")
    normalized_tests = []
    seen_tests = set()
    for test in tests:
        if not isinstance(test, Mapping):
            raise ValueError("run tests must be objects")
        test_id = str(test.get("id") or "")
        status = str(test.get("status") or "")
        if not test_id or test_id in seen_tests or status not in TEST_STATUSES:
            raise ValueError("run tests require unique ids and valid statuses")
        seen_tests.add(test_id)
        normalized_tests.append({"id": test_id, "status": status})
    normalized_tests.sort(key=lambda item: item["id"])
    baseline_tests = outcome.get("baseline_tests") or []
    if not isinstance(baseline_tests, list):
        raise ValueError("baseline_tests must be a list")
    normalized_baseline_tests = []
    seen_baseline_tests = set()
    for test in baseline_tests:
        if not isinstance(test, Mapping):
            raise ValueError("baseline tests must be objects")
        test_id = str(test.get("id") or "")
        status = str(test.get("status") or "")
        if not test_id or test_id in seen_baseline_tests or status not in TEST_STATUSES:
            raise ValueError("baseline tests require unique ids and valid statuses")
        seen_baseline_tests.add(test_id)
        normalized_baseline_tests.append({"id": test_id, "status": status})
    normalized_baseline_tests.sort(key=lambda item: item["id"])

    patch_produced = outcome.get("patch_produced")
    if not isinstance(patch_produced, bool):
        raise ValueError("run outcome requires patch_produced boolean")
    patch_sha256 = outcome.get("patch_sha256")
    if patch_produced:
        if not isinstance(patch_sha256, str) or len(patch_sha256) != 64:
            raise ValueError("produced patches require a SHA-256 digest")
        try:
            int(patch_sha256, 16)
        except ValueError:
            raise ValueError("patch_sha256 must be hexadecimal")
    elif patch_sha256 is not None:
        raise ValueError("a run without a patch cannot record patch_sha256")

    first_edit = outcome.get("first_proposed_edit")
    if first_edit is not None:
        if not isinstance(first_edit, Mapping) or not str(first_edit.get("path") or ""):
            raise ValueError("first_proposed_edit requires a path")
        first_edit = deepcopy(dict(first_edit))
    unsupported = sorted(
        _strings(outcome.get("unsupported_claims") or [], "unsupported claims")
    )
    for key in ("repository_searches", "extra_context_requests"):
        value = outcome.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError("%s must be a non-negative integer" % key)
    elapsed = outcome.get("elapsed_seconds")
    if not isinstance(elapsed, (int, float)) or float(elapsed) < 0.0:
        raise ValueError("elapsed_seconds must be non-negative")
    usage = outcome.get("usage") or {}
    if not isinstance(usage, Mapping) or any(
        not isinstance(value, (int, float)) or float(value) < 0.0
        for value in usage.values()
    ):
        raise ValueError("usage values must be non-negative numbers")

    return {
        "patch_produced": patch_produced,
        "patch_sha256": patch_sha256,
        "changed_files": changed_files,
        "baseline_tests": normalized_baseline_tests,
        "tests": normalized_tests,
        "first_proposed_edit": first_edit,
        "unsupported_claims": unsupported,
        "repository_searches": int(outcome["repository_searches"]),
        "extra_context_requests": int(outcome["extra_context_requests"]),
        "elapsed_seconds": float(elapsed),
        "usage": {str(key): value for key, value in sorted(usage.items())},
    }


def create_run_manifest(
    spec: Mapping[str, Any],
    agent_input: Mapping[str, Any],
    *,
    attempt: int,
    agent: Mapping[str, Any],
    outcome: Mapping[str, Any],
    started_at: str,
    finished_at: str,
) -> Dict[str, Any]:
    """Create a content-addressed immutable record of one completed AI run."""
    validate_spec(spec)
    validate_agent_input(spec, agent_input)
    task_id = str((agent_input.get("task") or {}).get("id") or "")
    arm = str(agent_input.get("arm") or "")
    if task_id not in _task_index(spec) or arm not in ARMS:
        raise ValueError("agent input has an invalid task or arm")
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("run attempt must be a positive integer")
    if not isinstance(agent, Mapping):
        raise ValueError("run requires agent identity")
    for key in ("provider", "model"):
        if not str(agent.get(key) or ""):
            raise ValueError("agent identity requires %s" % key)
    if not started_at or not finished_at:
        raise ValueError("run timestamps are required")

    manifest = {
        "schema": RUN_SCHEMA,
        "benchmark_hash": content_hash(spec),
        "agent_input_hash": content_hash(agent_input),
        "task_id": task_id,
        "arm": arm,
        "attempt": attempt,
        "repository": deepcopy(dict(agent_input["task"]["repository"])),
        "agent": deepcopy(dict(agent)),
        "context_schema": (
            str((agent_input.get("context") or {}).get("schema") or "") or None
        ),
        "started_at": str(started_at),
        "finished_at": str(finished_at),
        "outcome": _validate_outcome(outcome),
    }
    manifest["manifest_id"] = content_hash(manifest)
    return manifest


def validate_manifest(spec: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    validate_spec(spec)
    if manifest.get("schema") != RUN_SCHEMA:
        raise ValueError("unsupported AI repair run schema")
    if manifest.get("benchmark_hash") != content_hash(spec):
        raise ValueError("run manifest benchmark hash mismatch")
    task_id = str(manifest.get("task_id") or "")
    if task_id not in _task_index(spec):
        raise ValueError("run manifest references an unknown task")
    if str(manifest.get("arm") or "") not in ARMS:
        raise ValueError("run manifest references an unknown arm")
    if manifest.get("repository") != _task_index(spec)[task_id]["repository"]:
        raise ValueError("run manifest repository identity mismatch")
    if not isinstance(manifest.get("attempt"), int) or manifest["attempt"] < 1:
        raise ValueError("run manifest attempt must be positive")
    agent = manifest.get("agent") or {}
    if not isinstance(agent, Mapping) or any(
        not str(agent.get(key) or "") for key in ("provider", "model")
    ):
        raise ValueError("run manifest requires provider and model identity")
    if not str(manifest.get("started_at") or "") or not str(
        manifest.get("finished_at") or ""
    ):
        raise ValueError("run manifest requires timestamps")
    expected_id = content_hash(
        {key: value for key, value in manifest.items() if key != "manifest_id"}
    )
    if manifest.get("manifest_id") != expected_id:
        raise ValueError("immutable run manifest identity mismatch")
    _validate_outcome(manifest.get("outcome") or {})


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator else None


def _change_set_score(
    changed: Sequence[str], change_set: Mapping[str, Any]
) -> Tuple[Tuple[float, float, int], Dict[str, Any]]:
    changed_set = set(changed)
    required = set(change_set["required_files"])
    allowed = set(change_set["allowed_files"])
    required_hits = len(changed_set & required)
    required_recall = _ratio(required_hits, len(required)) or 0.0
    allowed_hits = len(changed_set & allowed)
    allowed_precision = _ratio(allowed_hits, len(changed_set))
    unnecessary = sorted(changed_set - allowed)
    result = {
        "required_file_recall": required_recall,
        "allowed_file_precision": allowed_precision,
        "missing_required_files": sorted(required - changed_set),
        "unnecessary_changed_files": unnecessary,
        "matched_required_files": sorted(changed_set & required),
    }
    ordering = (
        required_recall,
        allowed_precision if allowed_precision is not None else 0.0,
        -len(unnecessary),
    )
    return ordering, result


def score_manifest(
    spec: Mapping[str, Any], manifest: Mapping[str, Any]
) -> Dict[str, Any]:
    validate_manifest(spec, manifest)
    task = _task_index(spec)[str(manifest["task_id"])]
    oracle = task["oracle"]
    outcome = manifest["outcome"]
    changed = list(outcome["changed_files"])
    alternatives = [
        _change_set_score(changed, change_set)
        for change_set in oracle["acceptable_change_sets"]
    ]
    _, change_score = max(alternatives, key=lambda item: item[0])

    statuses = {str(test["id"]): str(test["status"]) for test in outcome["tests"]}
    required_test_ids = [str(test["id"]) for test in oracle["required_tests"]]
    passed_tests = sum(
        statuses.get(test_id) == "passed" for test_id in required_test_ids
    )
    required_test_pass_rate = passed_tests / float(len(required_test_ids))
    all_required_tests_passed = passed_tests == len(required_test_ids)
    forbidden = sorted(set(changed) & set(oracle.get("forbidden_files") or []))
    first_edit = outcome.get("first_proposed_edit") or {}
    all_allowed = set()
    for change_set in oracle["acceptable_change_sets"]:
        all_allowed.update(change_set["allowed_files"])
    first_edit_allowed = (
        str(first_edit.get("path") or "") in all_allowed if first_edit else None
    )
    oracle_passed = bool(
        outcome["patch_produced"]
        and all_required_tests_passed
        and change_score["required_file_recall"] == 1.0
        and not forbidden
    )
    strict_success = bool(
        oracle_passed and not change_score["unnecessary_changed_files"]
    )
    return {
        "manifest_id": str(manifest["manifest_id"]),
        "task_id": str(manifest["task_id"]),
        "arm": str(manifest["arm"]),
        "attempt": int(manifest["attempt"]),
        "oracle_passed": oracle_passed,
        "strict_success": strict_success,
        "required_test_pass_rate": required_test_pass_rate,
        "all_required_tests_passed": all_required_tests_passed,
        **change_score,
        "forbidden_changed_files": forbidden,
        "first_edit_allowed": first_edit_allowed,
        "unsupported_claim_count": len(outcome["unsupported_claims"]),
        "repository_searches": int(outcome["repository_searches"]),
        "extra_context_requests": int(outcome["extra_context_requests"]),
        "elapsed_seconds": float(outcome["elapsed_seconds"]),
        "usage": dict(outcome["usage"]),
    }


def _mean(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return sum(values) / len(values) if values else None


def compare_manifests(
    spec: Mapping[str, Any], manifests: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    validate_spec(spec)
    if not manifests:
        raise ValueError("comparison requires run manifests")
    seen = set()
    scores = []
    for manifest in manifests:
        score = score_manifest(spec, manifest)
        key = (score["task_id"], score["arm"], score["attempt"])
        if key in seen:
            raise ValueError("comparison repeats a task/arm/attempt run")
        seen.add(key)
        scores.append(score)

    numeric_keys = (
        "oracle_passed",
        "strict_success",
        "required_test_pass_rate",
        "required_file_recall",
        "allowed_file_precision",
        "first_edit_allowed",
        "unsupported_claim_count",
        "repository_searches",
        "extra_context_requests",
        "elapsed_seconds",
    )
    arm_results = {}
    for arm in ARMS:
        rows = [row for row in scores if row["arm"] == arm]
        if not rows:
            continue
        arm_results[arm] = {
            "run_count": len(rows),
            **{key: _mean(rows, key) for key in numeric_keys},
            "input_tokens": _mean([row["usage"] for row in rows], "input_tokens"),
            "output_tokens": _mean([row["usage"] for row in rows], "output_tokens"),
        }
    baseline = arm_results.get("unassisted")
    deltas = {}
    if baseline:
        for arm, metrics in arm_results.items():
            if arm == "unassisted":
                continue
            deltas[arm] = {
                key: (
                    float(metrics[key]) - float(baseline[key])
                    if isinstance(metrics.get(key), (int, float))
                    and isinstance(baseline.get(key), (int, float))
                    else None
                )
                for key in numeric_keys
            }

    expected = {(str(task["id"]), arm) for task in spec["tasks"] for arm in ARMS}
    observed = {(row["task_id"], row["arm"]) for row in scores}
    missing = [
        {"task_id": task_id, "arm": arm} for task_id, arm in sorted(expected - observed)
    ]
    return {
        "schema": COMPARISON_SCHEMA,
        "benchmark_hash": content_hash(spec),
        "evaluation_tier": str(spec["evaluation_tier"]),
        "run_count": len(scores),
        "complete_task_arm_matrix": not missing,
        "missing_task_arms": missing,
        "arms": arm_results,
        "deltas_from_unassisted": deltas,
        "runs": sorted(
            scores,
            key=lambda row: (row["task_id"], row["arm"], row["attempt"]),
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manage R1 AI repair benchmark data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("spec")
    payload_parser = subparsers.add_parser("payload")
    payload_parser.add_argument("spec")
    payload_parser.add_argument("--task", required=True)
    payload_parser.add_argument("--arm", choices=ARMS, required=True)
    payload_parser.add_argument("--context")
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("spec")
    score_parser.add_argument("manifest")
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("spec")
    compare_parser.add_argument("manifests", nargs="+")
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("spec")
    manifest_parser.add_argument("agent_input")
    manifest_parser.add_argument("outcome")
    manifest_parser.add_argument("--attempt", type=int, required=True)
    manifest_parser.add_argument("--provider", required=True)
    manifest_parser.add_argument("--model", required=True)
    manifest_parser.add_argument("--started-at", required=True)
    manifest_parser.add_argument("--finished-at", required=True)
    for item in (
        validate_parser,
        payload_parser,
        score_parser,
        compare_parser,
        manifest_parser,
    ):
        item.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    spec = load_json(Path(args.spec))
    if args.command == "validate":
        validate_spec(spec)
        result = {
            "schema": BENCHMARK_SCHEMA,
            "status": "valid",
            "benchmark_hash": content_hash(spec),
            "task_count": len(spec["tasks"]),
            "evaluation_tier": spec["evaluation_tier"],
        }
    elif args.command == "payload":
        context = load_json(Path(args.context)) if args.context else None
        result = build_agent_input(spec, args.task, args.arm, context)
    elif args.command == "score":
        result = score_manifest(spec, load_json(Path(args.manifest)))
    elif args.command == "compare":
        manifests = [load_json(Path(path)) for path in args.manifests]
        result = compare_manifests(spec, manifests)
    else:
        result = create_run_manifest(
            spec,
            load_json(Path(args.agent_input)),
            attempt=args.attempt,
            agent={"provider": args.provider, "model": args.model},
            outcome=load_json(Path(args.outcome)),
            started_at=args.started_at,
            finished_at=args.finished_at,
        )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
