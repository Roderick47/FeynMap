"""Bridge FeynMap R1 to real SWE-bench repair tasks.

The bridge deliberately separates four phases.

Phase one, select, sees only issue and repository metadata and never gold
patches or tests. Phase two, prepare, runs only after selection is frozen. It
may read the gold patch to construct hidden changed-file diagnostics, prepares
the buggy base checkout, and emits a normal R1 held-out benchmark spec. Phase
three converts one trusted command-agent run into an official SWE-bench
prediction plus an immutable FeynMap generation record. Phase four joins those
generation records with official SWE-bench report files.

Official resolved status is the primary success metric. FeynMap file
localization and efficiency measurements are secondary diagnostics.

No Hugging Face or SWE-bench package is a core dependency. Dataset input may be
JSON or JSONL, or an optional Hugging Face dataset when datasets is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .ai_repair_benchmark import (
    ARMS,
    REPOSITORY_CONTENT_HASH_POLICY,
    build_agent_input,
    content_hash,
    load_json,
    validate_spec,
)
from .ai_repair_execution import (
    AgentRunResult,
    CommandRepairAgent,
    _copy_repository,
    capture_patch,
    repository_content_hash,
    resolve_source_repository,
)
from .ai_repair_holdout import build_holdout_lock, validate_holdout_spec

SELECTION_SCHEMA = "feynmap.swebench_r1_selection.v1"
GENERATION_SCHEMA = "feynmap.swebench_r1_generation.v1"
REPORT_SCHEMA = "feynmap.swebench_r1_report.v1"

GOLD_KEYS = {
    "patch",
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "fail_to_pass",
    "pass_to_pass",
    "hints_text",
}
REQUIRED_DATASET_KEYS = (
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_rows_from_path(path: Path) -> List[Mapping[str, Any]]:
    if not path.is_file():
        raise ValueError("dataset file does not exist: %s" % path)
    if path.suffix.casefold() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise ValueError("JSONL row %d must be an object" % number)
                rows.append(value)
        return rows

    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if isinstance(value, Mapping) and isinstance(value.get("data"), list):
        value = value["data"]
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ValueError("dataset JSON must contain a list of objects")
    return list(value)


def load_dataset_rows(
    source: str,
    *,
    split: str = "test",
) -> List[Mapping[str, Any]]:
    """Load local JSON/JSONL or an optional Hugging Face dataset."""
    candidate = Path(source)
    if candidate.exists():
        return _load_rows_from_path(candidate)

    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        raise RuntimeError(
            "non-file dataset sources require the optional 'datasets' package"
        )
    rows = load_dataset(source, split=split)
    return [dict(row) for row in rows]


def _safe_projection(row: Mapping[str, Any]) -> Dict[str, str]:
    missing = [key for key in REQUIRED_DATASET_KEYS if not str(row.get(key) or "")]
    if missing:
        raise ValueError("SWE-bench row missing fields: %s" % ", ".join(missing))
    return {
        "instance_id": str(row["instance_id"]),
        "repo": str(row["repo"]),
        "base_commit": str(row["base_commit"]),
        "problem_statement": str(row["problem_statement"]),
        "version": str(row.get("version") or ""),
    }


def _selection_rank(corpus_id: str, instance_id: str) -> str:
    return hashlib.sha256(
        ("%s|%s" % (corpus_id, instance_id)).encode("utf-8")
    ).hexdigest()


def build_selection(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_name: str,
    split: str,
    corpus_id: str,
    count: int = 8,
    max_per_repo: int = 2,
    selected_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Select a deterministic corpus without touching patch/test fields."""
    if count < 5:
        raise ValueError("real-world R1 selection requires at least 5 tasks")
    if max_per_repo <= 0:
        raise ValueError("max_per_repo must be positive")

    safe_rows = [_safe_projection(row) for row in rows]
    ids = [row["instance_id"] for row in safe_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("SWE-bench instance ids must be unique")

    ordered = sorted(
        safe_rows,
        key=lambda row: (
            _selection_rank(corpus_id, row["instance_id"]),
            row["instance_id"],
        ),
    )
    selected = []
    repo_counts: Counter = Counter()
    for row in ordered:
        if repo_counts[row["repo"]] >= max_per_repo:
            continue
        selected.append(row)
        repo_counts[row["repo"]] += 1
        if len(selected) >= count:
            break
    if len(selected) < count:
        raise ValueError(
            "only %d tasks satisfy selection constraints; requested %d"
            % (len(selected), count)
        )

    result = {
        "schema": SELECTION_SCHEMA,
        "dataset_name": str(dataset_name),
        "split": str(split),
        "corpus_id": str(corpus_id),
        "selected_at": str(selected_at or _utc_now()),
        "selection_policy": {
            "gold_fields_visible": False,
            "ordering": "sha256(corpus_id|instance_id)",
            "max_per_repo": int(max_per_repo),
            "requested_count": int(count),
            "excluded_gold_keys": sorted(GOLD_KEYS),
        },
        "tasks": selected,
    }
    result["selection_id"] = content_hash(result)
    return result


def validate_selection(
    selection: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    if selection.get("schema") != SELECTION_SCHEMA:
        raise ValueError("unsupported SWE-bench R1 selection schema")
    expected_id = content_hash(
        {key: value for key, value in selection.items() if key != "selection_id"}
    )
    if selection.get("selection_id") != expected_id:
        raise ValueError("SWE-bench selection identity mismatch")

    dataset = {
        projection["instance_id"]: projection
        for projection in (_safe_projection(row) for row in rows)
    }
    for selected in selection.get("tasks") or []:
        instance_id = str(selected.get("instance_id") or "")
        if instance_id not in dataset or dict(selected) != dataset[instance_id]:
            raise ValueError(
                "selection no longer matches dataset metadata: %s" % instance_id
            )


def _dataset_index(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    indexed = {}
    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        if not instance_id or instance_id in indexed:
            raise ValueError("dataset requires unique non-empty instance ids")
        indexed[instance_id] = row
    return indexed


def _run_git(argv: Sequence[str], *, cwd: Optional[Path] = None) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git command failed (%s): %s"
            % (" ".join(argv), completed.stderr.strip())
        )
    return completed.stdout.strip()


def prepare_checkout(
    repository: str,
    base_commit: str,
    destination: Path,
    cache_root: Path,
    *,
    reuse_existing: bool = False,
) -> Path:
    """Prepare one detached historical checkout using a shared clone cache."""
    slug = repository.replace("/", "__")
    cache = cache_root / slug
    destination = destination.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not cache.exists():
        _run_git(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "https://github.com/%s.git" % repository,
                str(cache),
            ]
        )

    if destination.exists():
        if not reuse_existing:
            raise ValueError("prepared checkout already exists: %s" % destination)
        head = _run_git(["git", "-C", str(destination), "rev-parse", "HEAD"])
        if head != base_commit:
            raise ValueError(
                "existing checkout revision mismatch for %s" % destination
            )
        return destination

    try:
        _run_git(
            ["git", "-C", str(cache), "cat-file", "-e", "%s^{commit}" % base_commit]
        )
    except RuntimeError:
        _run_git(
            [
                "git",
                "-C",
                str(cache),
                "fetch",
                "--filter=blob:none",
                "origin",
                base_commit,
            ]
        )

    _run_git(
        [
            "git",
            "-C",
            str(cache),
            "worktree",
            "add",
            "--detach",
            str(destination),
            base_commit,
        ]
    )
    return destination


def _patch_paths(patch: str) -> List[str]:
    paths = []
    seen = set()
    for line in str(patch or "").splitlines():
        if not line.startswith("+++ b/"):
            continue
        path = line[6:].strip()
        if path == "/dev/null" or not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def prepare_benchmark_spec(
    rows: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any],
    *,
    project_root: Path,
    checkout_root: Path,
    cache_root: Path,
    reuse_existing: bool = False,
) -> Dict[str, Any]:
    """Materialize selected buggy revisions and seal their R1 benchmark spec."""
    validate_selection(selection, rows)
    indexed = _dataset_index(rows)
    tasks = []
    for selected in selection["tasks"]:
        instance_id = str(selected["instance_id"])
        source = indexed[instance_id]
        repo = str(selected["repo"])
        base_commit = str(selected["base_commit"])
        checkout = prepare_checkout(
            repo,
            base_commit,
            checkout_root / instance_id,
            cache_root,
            reuse_existing=reuse_existing,
        )
        repo_hash = repository_content_hash(
            checkout, policy=REPOSITORY_CONTENT_HASH_POLICY
        )

        changed = _patch_paths(str(source.get("patch") or ""))
        if not changed:
            raise ValueError(
                "selected SWE-bench task has no parseable gold patch files: %s"
                % instance_id
            )

        tasks.append(
            {
                "id": instance_id,
                "description": str(selected["problem_statement"]),
                "repository": {
                    "locator": "path:%s" % checkout.resolve(),
                    "revision": base_commit,
                    "content_hash_policy": REPOSITORY_CONTENT_HASH_POLICY,
                    "content_hash": repo_hash,
                },
                "oracle": {
                    "required_tests": [
                        {
                            "id": "swebench-resolved",
                            "command": ["external:swebench"],
                        }
                    ],
                    "acceptable_change_sets": [
                        {
                            "required_files": changed,
                            "allowed_files": changed,
                        }
                    ],
                    "forbidden_files": [],
                    "sealed_files": [],
                    "baseline_expectation": "at_least_one_failure",
                },
                "admission": {
                    "source_group": repo,
                    "source_reference": instance_id,
                    "selection_reason": (
                        "Chosen by predeclared hash ordering and repository cap "
                        "before gold patch/test fields were consulted."
                    ),
                    "used_for_policy_tuning": False,
                    "solution_inspected_before_selection": False,
                },
                "external_evaluator": {
                    "kind": "swebench",
                    "dataset_name": str(selection["dataset_name"]),
                    "split": str(selection["split"]),
                    "instance_id": instance_id,
                    "repo": repo,
                    "base_commit": base_commit,
                    "gold_changed_files_proxy": changed,
                },
            }
        )

    spec = {
        "schema": "feynmap.ai_repair_benchmark.v1",
        "name": "R1 SWE-bench held-out real-world repair corpus",
        "evaluation_tier": "held_out",
        "arms": list(ARMS),
        "holdout": {
            "corpus_id": str(selection["corpus_id"]),
            "selection_policy": _canonical_json(selection["selection_policy"]),
            "selected_at": str(selection["selected_at"]),
            "selection_owner": "feynmap.swebench_r1.select",
            "assisted_results_observed_before_freeze": False,
            "policy_tuning_allowed_after_freeze": False,
            "selection_id": str(selection["selection_id"]),
        },
        "tasks": tasks,
    }
    validate_holdout_spec(spec)
    return spec


def _task(spec: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    for task in spec["tasks"]:
        if str(task["id"]) == task_id:
            return task
    raise ValueError("unknown R1 task: %s" % task_id)


def generate_prediction(
    spec: Mapping[str, Any],
    task_id: str,
    arm: str,
    *,
    project_root: Path,
    context: Optional[Mapping[str, Any]],
    agent: CommandRepairAgent,
) -> Dict[str, Any]:
    """Run one trusted repair agent without grading; return SWE-bench prediction."""
    validate_spec(spec)
    task = _task(spec, task_id)
    evaluator = task.get("external_evaluator") or {}
    if evaluator.get("kind") != "swebench":
        raise ValueError("task is not configured for SWE-bench evaluation")

    agent_input = build_agent_input(spec, task_id, arm, context)
    source = resolve_source_repository(
        project_root, str(task["repository"]["locator"])
    )
    expected_hash = str(task["repository"]["content_hash"])
    actual_hash = repository_content_hash(
        source, policy=str(task["repository"]["content_hash_policy"])
    )
    if actual_hash != expected_hash:
        raise ValueError("prepared SWE-bench source repository content drifted")

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="feynmap-swebench-r1-") as temp:
        control = Path(temp) / "control"
        baseline = Path(temp) / "baseline"
        workspace = Path(temp) / "workspace"
        control.mkdir()
        _copy_repository(source, baseline)
        _copy_repository(source, workspace)
        result: AgentRunResult = agent.run(workspace, agent_input, control)
        changed_files, patch, patch_sha256 = capture_patch(baseline, workspace)
    elapsed = time.perf_counter() - started

    record = {
        "schema": GENERATION_SCHEMA,
        "benchmark_hash": content_hash(spec),
        "task_id": task_id,
        "instance_id": str(evaluator["instance_id"]),
        "arm": arm,
        "context_hash": content_hash(context) if context is not None else None,
        "repository": dict(task["repository"]),
        "agent": {"provider": result.provider, "model": result.model},
        "prediction": {
            "instance_id": str(evaluator["instance_id"]),
            "model_name_or_path": "%s/%s" % (result.model, arm),
            "model_patch": patch,
        },
        "outcome": {
            "patch_produced": bool(patch),
            "patch_sha256": patch_sha256 if patch else None,
            "changed_files": changed_files,
            "first_proposed_edit": result.first_proposed_edit,
            "unsupported_claims": list(result.unsupported_claims),
            "repository_searches": int(result.repository_searches),
            "extra_context_requests": int(result.extra_context_requests),
            "elapsed_seconds": round(elapsed, 6),
            "usage": dict(result.usage),
        },
    }
    record["generation_id"] = content_hash(record)
    return record


def _load_generation_records(paths: Sequence[Path]) -> List[Mapping[str, Any]]:
    records = []
    for path in paths:
        value = load_json(path)
        if value.get("schema") != GENERATION_SCHEMA:
            raise ValueError("unsupported generation record: %s" % path)
        expected = content_hash(
            {key: item for key, item in value.items() if key != "generation_id"}
        )
        if value.get("generation_id") != expected:
            raise ValueError("generation identity mismatch: %s" % path)
        records.append(value)
    return records


def export_predictions(
    records: Sequence[Mapping[str, Any]],
    *,
    arm: Optional[str] = None,
) -> str:
    selected = [
        record for record in records if arm is None or str(record["arm"]) == arm
    ]
    if not selected:
        raise ValueError("no generation records selected")
    seen = set()
    lines = []
    for record in sorted(selected, key=lambda row: str(row["instance_id"])):
        instance_id = str(record["instance_id"])
        if instance_id in seen:
            raise ValueError("duplicate prediction for instance: %s" % instance_id)
        seen.add(instance_id)
        lines.append(_canonical_json(record["prediction"]))
    return "\n".join(lines) + "\n"


def _report_path(
    run_root: Path,
    record: Mapping[str, Any],
) -> Path:
    model = str(record["prediction"]["model_name_or_path"]).replace("/", "__")
    return run_root / model / str(record["instance_id"]) / "report.json"


def _safe_ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / float(denominator) if denominator else None


def _proxy_file_metrics(
    changed: Sequence[str],
    gold: Sequence[str],
) -> Dict[str, Any]:
    changed_set = set(changed)
    gold_set = set(gold)
    hits = changed_set & gold_set
    return {
        "gold_changed_file_recall_proxy": _safe_ratio(len(hits), len(gold_set)),
        "changed_file_precision_proxy": _safe_ratio(len(hits), len(changed_set)),
        "missing_gold_changed_files_proxy": sorted(gold_set - changed_set),
        "extra_changed_files_proxy": sorted(changed_set - gold_set),
    }


def aggregate_results(
    spec: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    run_root: Path,
) -> Dict[str, Any]:
    """Join official SWE-bench reports to FeynMap generation telemetry."""
    validate_spec(spec)
    task_index = {str(task["id"]): task for task in spec["tasks"]}
    rows = []
    for record in records:
        task_id = str(record["task_id"])
        if task_id not in task_index:
            raise ValueError("generation record is not in benchmark: %s" % task_id)
        if record.get("benchmark_hash") != content_hash(spec):
            raise ValueError("generation record benchmark hash mismatch")
        path = _report_path(run_root, record)
        if not path.is_file():
            raise ValueError("missing official SWE-bench report: %s" % path)
        report = load_json(path)
        instance_id = str(record["instance_id"])
        detail = report.get(instance_id)
        if not isinstance(detail, Mapping):
            raise ValueError("SWE-bench report missing instance: %s" % instance_id)

        task = task_index[task_id]
        gold = (
            task.get("external_evaluator") or {}
        ).get("gold_changed_files_proxy") or []
        file_metrics = _proxy_file_metrics(
            record["outcome"]["changed_files"], gold
        )
        first = record["outcome"].get("first_proposed_edit") or {}
        first_path = str(first.get("path") or "")
        usage = record["outcome"].get("usage") or {}
        rows.append(
            {
                "task_id": task_id,
                "instance_id": instance_id,
                "arm": str(record["arm"]),
                "resolved": bool(detail.get("resolved")),
                "patch_exists": bool(detail.get("patch_exists")),
                "patch_successfully_applied": bool(
                    detail.get("patch_successfully_applied")
                ),
                "infra_failure": bool(detail.get("infra_failure")),
                "first_edit_gold_file_proxy": (
                    first_path in set(gold) if first_path else None
                ),
                **file_metrics,
                "repository_searches": int(
                    record["outcome"].get("repository_searches") or 0
                ),
                "extra_context_requests": int(
                    record["outcome"].get("extra_context_requests") or 0
                ),
                "unsupported_claim_count": len(
                    record["outcome"].get("unsupported_claims") or []
                ),
                "elapsed_seconds": float(
                    record["outcome"].get("elapsed_seconds") or 0.0
                ),
                "input_tokens": float(usage.get("input_tokens") or 0.0),
                "output_tokens": float(usage.get("output_tokens") or 0.0),
            }
        )

    by_arm = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        if not arm_rows:
            continue

        def avg(key: str) -> Optional[float]:
            values = [
                float(row[key])
                for row in arm_rows
                if isinstance(row.get(key), (int, float, bool))
                and row.get(key) is not None
            ]
            return sum(values) / len(values) if values else None

        by_arm[arm] = {
            "attempted": len(arm_rows),
            "resolved_rate": avg("resolved"),
            "patch_apply_rate": avg("patch_successfully_applied"),
            "infra_failure_rate": avg("infra_failure"),
            "first_edit_gold_file_proxy_rate": avg("first_edit_gold_file_proxy"),
            "gold_changed_file_recall_proxy": avg(
                "gold_changed_file_recall_proxy"
            ),
            "changed_file_precision_proxy": avg(
                "changed_file_precision_proxy"
            ),
            "mean_repository_searches": avg("repository_searches"),
            "mean_extra_context_requests": avg("extra_context_requests"),
            "mean_unsupported_claims": avg("unsupported_claim_count"),
            "mean_elapsed_seconds": avg("elapsed_seconds"),
            "mean_input_tokens": avg("input_tokens"),
            "mean_output_tokens": avg("output_tokens"),
        }

    baseline = by_arm.get("unassisted")
    deltas = {}
    if baseline is not None:
        for arm, summary in by_arm.items():
            if arm == "unassisted":
                continue
            arm_deltas = {}
            for key, value in summary.items():
                base = baseline.get(key)
                if isinstance(value, (int, float)) and isinstance(base, (int, float)):
                    arm_deltas[key] = float(value) - float(base)
            deltas[arm] = arm_deltas

    result = {
        "schema": REPORT_SCHEMA,
        "benchmark_hash": content_hash(spec),
        "task_count": len(task_index),
        "generation_count": len(records),
        "primary_metric": "official_swebench_resolved_rate",
        "secondary_metric_warning": (
            "gold changed-file metrics are proxies derived from the reference "
            "patch; alternative correct repairs may change different files."
        ),
        "by_arm": by_arm,
        "deltas_from_unassisted": deltas,
        "rows": sorted(rows, key=lambda row: (row["task_id"], row["arm"])),
    }
    result["report_id"] = content_hash(result)
    return result


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run FeynMap R1 against real SWE-bench repair tasks"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    select = sub.add_parser("select")
    select.add_argument("source")
    select.add_argument("--dataset-name")
    select.add_argument("--split", default="test")
    select.add_argument("--corpus-id", default="feynmap-r1-swebench-v1")
    select.add_argument("--count", type=int, default=8)
    select.add_argument("--max-per-repo", type=int, default=2)
    select.add_argument("--output", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("source")
    prepare.add_argument("selection")
    prepare.add_argument("--split", default="test")
    prepare.add_argument("--project-root", default=".")
    prepare.add_argument("--checkout-root", required=True)
    prepare.add_argument("--cache-root", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--lock-output", required=True)
    prepare.add_argument("--reuse-existing", action="store_true")

    predict = sub.add_parser("record-prediction")
    predict.add_argument("spec")
    predict.add_argument("--task", required=True)
    predict.add_argument("--arm", required=True, choices=ARMS)
    predict.add_argument("--context")
    predict.add_argument("--project-root", default=".")
    predict.add_argument("--provider", required=True)
    predict.add_argument("--model", required=True)
    predict.add_argument("--agent-timeout", type=float, default=900.0)
    predict.add_argument("--pass-env", action="append", default=[])
    predict.add_argument("--output", required=True)
    predict.add_argument("agent_command", nargs=argparse.REMAINDER)

    export = sub.add_parser("export-predictions")
    export.add_argument("records", nargs="+")
    export.add_argument("--arm", choices=ARMS)
    export.add_argument("--output", required=True)

    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("spec")
    aggregate.add_argument("records", nargs="+")
    aggregate.add_argument("--run-root", required=True)
    aggregate.add_argument("--output")
    aggregate.add_argument("--pretty", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "select":
        dataset_name = args.dataset_name or args.source
        rows = load_dataset_rows(args.source, split=args.split)
        result = build_selection(
            rows,
            dataset_name=dataset_name,
            split=args.split,
            corpus_id=args.corpus_id,
            count=args.count,
            max_per_repo=args.max_per_repo,
        )
        _write_json(Path(args.output), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "prepare":
        rows = load_dataset_rows(args.source, split=args.split)
        selection = load_json(Path(args.selection))
        spec = prepare_benchmark_spec(
            rows,
            selection,
            project_root=Path(args.project_root),
            checkout_root=Path(args.checkout_root),
            cache_root=Path(args.cache_root),
            reuse_existing=args.reuse_existing,
        )
        lock = build_holdout_lock(spec)
        _write_json(Path(args.output), spec)
        _write_json(Path(args.lock_output), lock)
        print(
            json.dumps(
                {
                    "benchmark_spec": str(Path(args.output)),
                    "benchmark_hash": content_hash(spec),
                    "holdout_lock": str(Path(args.lock_output)),
                    "lock_id": lock["lock_id"],
                    "task_count": len(spec["tasks"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "record-prediction":
        spec = load_json(Path(args.spec))
        context = load_json(Path(args.context)) if args.context else None
        command = list(args.agent_command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("an agent command must follow --")
        environment = {}
        for name in args.pass_env:
            if name not in os.environ:
                parser.error("requested environment variable is not set: %s" % name)
            environment[name] = os.environ[name]
        agent = CommandRepairAgent(
            command,
            provider=args.provider,
            model=args.model,
            timeout_seconds=args.agent_timeout,
            environment=environment,
        )
        record = generate_prediction(
            spec,
            args.task,
            args.arm,
            project_root=Path(args.project_root),
            context=context,
            agent=agent,
        )
        _write_json(Path(args.output), record)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0

    if args.command == "export-predictions":
        records = _load_generation_records([Path(path) for path in args.records])
        text_value = export_predictions(records, arm=args.arm)
        Path(args.output).write_text(text_value, encoding="utf-8")
        print(args.output)
        return 0

    spec = load_json(Path(args.spec))
    records = _load_generation_records([Path(path) for path in args.records])
    result = aggregate_results(spec, records, run_root=Path(args.run_root))
    if args.output:
        _write_json(Path(args.output), result)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
