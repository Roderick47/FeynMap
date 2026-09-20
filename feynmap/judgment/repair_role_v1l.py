"""Repair-role judgment v1L: ambiguity-aware label adjudication.

v1L keeps the v1J provider questions frozen and evaluates a new synthetic
corpus with predeclared primary and acceptable labels.  This separates model
errors from defensible taxonomy-boundary decisions without changing v1K after
observing its live results.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .jev import JevJudgmentProvider
from .repair_role_v1j import (
    REPAIR_ROLES,
    V1J_SCHEMA,
    _classification_metrics,
    _target_ranking,
    judge_task,
)
from .repair_role_v1j import validate_spec as validate_v1j_spec

V1L_SCHEMA = "feynmap.repair_role_v1l.v1"


def _label_key(label: Mapping[str, Any]) -> Tuple[bool, str]:
    return bool(label["semantic_relevance"]), str(label["repair_role"])


def _provider_spec(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a v1J-compatible copy containing no adjudication metadata."""
    tasks = []
    for source_task in spec["tasks"]:
        task = {key: value for key, value in source_task.items() if key != "candidates"}
        task["candidates"] = []
        for source_candidate in source_task["candidates"]:
            candidate = {
                key: value
                for key, value in source_candidate.items()
                if key != "adjudication"
            }
            candidate["gold"] = dict(source_candidate["adjudication"]["primary"])
            task["candidates"].append(candidate)
        tasks.append(task)
    return {"schema": V1J_SCHEMA, "tasks": tasks}


def validate_spec(spec: Mapping[str, Any]) -> None:
    """Validate primary labels, acceptable sets, rationales, and provider state."""
    if spec.get("schema") != V1L_SCHEMA:
        raise ValueError("unsupported repair-role v1L schema")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1L requires a non-empty tasks list")

    ambiguous = 0
    singleton = 0
    boundary_tags = set()
    for task in tasks:
        for candidate in task.get("candidates") or []:
            candidate_id = str(candidate.get("id") or "")
            adjudication = candidate.get("adjudication")
            if not isinstance(adjudication, Mapping):
                raise ValueError("candidate %s requires adjudication" % candidate_id)
            primary = adjudication.get("primary")
            acceptable = adjudication.get("acceptable_labels")
            rationale = str(adjudication.get("rationale") or "").strip()
            if not isinstance(primary, Mapping):
                raise ValueError("candidate %s requires a primary label" % candidate_id)
            if not isinstance(acceptable, list) or not acceptable:
                raise ValueError(
                    "candidate %s requires acceptable labels" % candidate_id
                )
            if not rationale:
                raise ValueError(
                    "candidate %s requires an adjudication rationale" % candidate_id
                )

            labels = []
            for label in acceptable:
                if not isinstance(label, Mapping):
                    raise ValueError(
                        "candidate %s has an invalid acceptable label" % candidate_id
                    )
                relevance = label.get("semantic_relevance")
                role = str(label.get("repair_role") or "")
                if not isinstance(relevance, bool) or role not in REPAIR_ROLES:
                    raise ValueError(
                        "candidate %s has an invalid acceptable label" % candidate_id
                    )
                if relevance == (role == "incidental_context"):
                    raise ValueError(
                        "candidate %s has a cross-axis label conflict" % candidate_id
                    )
                labels.append((relevance, role))
            if len(labels) != len(set(labels)):
                raise ValueError(
                    "candidate %s repeats an acceptable label" % candidate_id
                )
            if _label_key(primary) not in labels:
                raise ValueError(
                    "candidate %s primary label must be acceptable" % candidate_id
                )

            if len(labels) > 1:
                ambiguous += 1
                if any(role == "implementation_target" for _, role in labels):
                    raise ValueError("implementation-target ambiguity is not allowed")
                boundary = str(adjudication.get("boundary") or "").strip()
                if not boundary:
                    raise ValueError(
                        "ambiguous candidate %s requires a boundary" % candidate_id
                    )
                boundary_tags.add(boundary)
            else:
                singleton += 1

    if not ambiguous or not singleton:
        raise ValueError("v1L requires both ambiguous and singleton labels")
    if len(boundary_tags) < 3:
        raise ValueError("v1L must cover at least three ambiguity boundaries")
    validate_v1j_spec(_provider_spec(spec))


def _acceptable_metrics(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    role_correct = 0
    relevance_correct = 0
    joint_correct = 0
    role_mass = 0.0
    joint_mass = 0.0
    ambiguous_joint = 0
    singleton_joint = 0
    ambiguous_count = 0
    singleton_count = 0
    for row in rows:
        labels = {_label_key(label) for label in row["acceptable_labels"]}
        roles = {role for _, role in labels}
        relevances = {relevance for relevance, _ in labels}
        predicted_role = str(row["predicted_repair_role"])
        relevance_probability = float(row["semantic_relevance_probability"])
        predicted_relevance = relevance_probability >= 0.5
        role_ok = predicted_role in roles
        relevance_ok = predicted_relevance in relevances
        joint_ok = (predicted_relevance, predicted_role) in labels
        role_correct += int(role_ok)
        relevance_correct += int(relevance_ok)
        joint_correct += int(joint_ok)

        probabilities = row["repair_role_probabilities"]
        role_mass += sum(float(probabilities[role]) for role in roles)
        joint_mass += sum(
            (relevance_probability if relevance else 1.0 - relevance_probability)
            * float(probabilities[role])
            for relevance, role in labels
        )
        if len(labels) > 1:
            ambiguous_count += 1
            ambiguous_joint += int(joint_ok)
        else:
            singleton_count += 1
            singleton_joint += int(joint_ok)

    count = len(rows)
    return {
        "candidate_count": count,
        "ambiguous_candidate_count": ambiguous_count,
        "singleton_candidate_count": singleton_count,
        "repair_role_acceptance_accuracy": role_correct / count if count else None,
        "semantic_relevance_acceptance_accuracy": (
            relevance_correct / count if count else None
        ),
        "joint_label_acceptance_accuracy": joint_correct / count if count else None,
        "ambiguous_joint_acceptance_accuracy": (
            ambiguous_joint / ambiguous_count if ambiguous_count else None
        ),
        "singleton_joint_acceptance_accuracy": (
            singleton_joint / singleton_count if singleton_count else None
        ),
        "mean_acceptable_role_probability_mass": role_mass / count if count else None,
        "mean_acceptable_joint_probability_mass": joint_mass / count if count else None,
    }


def _unaccepted_cases(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    cases = []
    for row in rows:
        predicted = (
            float(row["semantic_relevance_probability"]) >= 0.5,
            str(row["predicted_repair_role"]),
        )
        acceptable = {_label_key(label) for label in row["acceptable_labels"]}
        if predicted in acceptable:
            continue
        cases.append(
            {
                "task_id": str(row["task_id"]),
                "candidate_id": str(row["candidate_id"]),
                "region": dict(row["region"]),
                "primary_label": dict(row["primary_label"]),
                "acceptable_labels": [
                    dict(label) for label in row["acceptable_labels"]
                ],
                "predicted_semantic_relevance": predicted[0],
                "semantic_relevance_probability": float(
                    row["semantic_relevance_probability"]
                ),
                "predicted_repair_role": predicted[1],
                "repair_role_probabilities": dict(row["repair_role_probabilities"]),
            }
        )
    return cases


def run_experiment(spec: Mapping[str, Any], provider=None) -> Dict[str, Any]:
    validate_spec(spec)
    primary_counts = Counter(
        str(candidate["adjudication"]["primary"]["repair_role"])
        for task in spec["tasks"]
        for candidate in task["candidates"]
    )
    ambiguous_count = sum(
        len(candidate["adjudication"]["acceptable_labels"]) > 1
        for task in spec["tasks"]
        for candidate in task["candidates"]
    )
    output: Dict[str, Any] = {
        "schema": V1L_SCHEMA,
        "name": "Repair-role judgment v1L ambiguity-aware adjudication",
        "task_count": len(spec["tasks"]),
        "candidate_count": sum(len(task["candidates"]) for task in spec["tasks"]),
        "fixture_summary": {
            "primary_repair_role_counts": {
                role: primary_counts[role] for role in REPAIR_ROLES
            },
            "ambiguous_candidate_count": ambiguous_count,
            "adjudication_rationales_present": True,
            "adjudication_metadata_hidden_from_provider": True,
            "implementation_targets_singleton": True,
            "v1j_prompts_frozen": True,
            "wikonomi_tasks_used": False,
            "language_or_framework_rules": False,
        },
    }
    if provider is None:
        output["status"] = "fixture_validated"
        return output

    started = time.perf_counter()
    provider_spec = _provider_spec(spec)
    usage: Counter = Counter()
    task_results = []
    all_rows: List[Dict[str, Any]] = []
    task_rows = []
    for source_task, provider_task in zip(spec["tasks"], provider_spec["tasks"]):
        raw_rows, judgment, _ = judge_task(provider_task, provider)
        rows = []
        for row, candidate in zip(raw_rows, source_task["candidates"]):
            decorated = dict(row)
            adjudication = candidate["adjudication"]
            decorated["task_id"] = str(source_task["id"])
            decorated["primary_label"] = dict(adjudication["primary"])
            decorated["acceptable_labels"] = [
                dict(label) for label in adjudication["acceptable_labels"]
            ]
            decorated["ambiguous_label"] = len(decorated["acceptable_labels"]) > 1
            rows.append(decorated)
        all_rows.extend(rows)
        task_rows.append((str(source_task["id"]), rows))
        for key, value in judgment.usage.items():
            if isinstance(value, (int, float)):
                usage[key] += value
        task_result: Dict[str, Any] = {
            "id": str(source_task["id"]),
            "candidates": rows,
            "strict_primary_metrics": _classification_metrics(rows),
            "acceptable_label_metrics": _acceptable_metrics(rows),
            "provider": judgment.provider,
            "model": judgment.model,
        }
        if judgment.request_id:
            task_result["request_id"] = judgment.request_id
        task_results.append(task_result)

    output.update(
        {
            "status": "judged",
            "provider_elapsed_seconds": round(time.perf_counter() - started, 6),
            "strict_primary_metrics": _classification_metrics(all_rows),
            "acceptable_label_metrics": _acceptable_metrics(all_rows),
            "unaccepted_cases": _unaccepted_cases(all_rows),
            "target_ranking": _target_ranking(task_rows),
            "usage": dict(usage),
            "tasks": task_results,
        }
    )
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run ambiguity-aware repair-role judgment v1L fixtures"
    )
    parser.add_argument("--spec", default="experiments/repair_role_v1l.json")
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with Path(args.spec).open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    provider = JevJudgmentProvider() if args.jev else None
    result = run_experiment(spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
