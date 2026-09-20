"""Repair-role judgment v1K: adversarial task-conditioning evaluation.

v1K freezes the v1J role vocabulary and prompts.  It changes only the fixture
domain and evaluation: opaque candidate ids, role-swapping task pairs, multiple
edit targets, same-file regions, order invariance, relationship ablation, and
uncertainty/cross-axis diagnostics.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
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
from .repair_role_v1j import (
    validate_spec as validate_v1j_spec,
)

V1K_SCHEMA = "feynmap.repair_role_v1k.v1"
REQUIRED_CHALLENGES = {
    "multiple_targets",
    "opaque_ids",
    "order_invariance",
    "relationship_ablation",
    "same_file_regions",
    "suspicious_bridge",
    "task_conditioning",
}


def validate_spec(spec: Mapping[str, Any]) -> None:
    """Validate v1K and reuse all v1J label-leakage/region invariants."""
    if spec.get("schema") != V1K_SCHEMA:
        raise ValueError("unsupported repair-role v1K schema")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1K requires a non-empty tasks list")

    compatibility_spec = dict(spec)
    compatibility_spec["schema"] = V1J_SCHEMA
    validate_v1j_spec(compatibility_spec)

    observed_challenges = set()
    group_members: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for task in tasks:
        tags = task.get("challenge_tags") or []
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError("v1K challenge_tags must be a list of strings")
        observed_challenges.update(tags)
        for group_key in (
            "task_conditioning_group",
            "order_invariance_group",
            "relationship_ablation_group",
        ):
            value = task.get(group_key)
            if value:
                group_members[(group_key, str(value))].append(task)

        if "opaque_ids" in tags:
            for candidate in task["candidates"]:
                candidate_id = str(candidate["id"])
                if not candidate_id.startswith("region_"):
                    raise ValueError("opaque-id tasks require region_* candidate ids")
                if any(role in candidate_id for role in REPAIR_ROLES):
                    raise ValueError("opaque candidate id leaks a repair role")

        if "multiple_targets" in tags:
            targets = [
                item
                for item in task["candidates"]
                if item["gold"]["repair_role"] == "implementation_target"
            ]
            if len(targets) < 2:
                raise ValueError("multiple_targets tasks require at least two targets")

        if "same_file_regions" in tags:
            paths = [str(item["region"]["path"]) for item in task["candidates"]]
            if len(set(paths)) == len(paths):
                raise ValueError(
                    "same_file_regions tasks require repeated source paths"
                )

    missing = REQUIRED_CHALLENGES - observed_challenges
    if missing:
        raise ValueError(
            "v1K fixture corpus misses challenges: %s" % ", ".join(sorted(missing))
        )

    for (kind, name), members in group_members.items():
        if len(members) != 2:
            raise ValueError("%s %s must contain exactly two tasks" % (kind, name))
        candidate_sets = [
            {str(item["id"]) for item in task["candidates"]} for task in members
        ]
        if candidate_sets[0] != candidate_sets[1]:
            raise ValueError("comparison group %s must use identical candidates" % name)
        candidate_orders = [
            [str(item["id"]) for item in task["candidates"]] for task in members
        ]
        if kind == "order_invariance_group":
            if candidate_orders[0] == candidate_orders[1]:
                raise ValueError(
                    "order-invariance group %s must change candidate order" % name
                )
        elif candidate_orders[0] != candidate_orders[1]:
            raise ValueError("comparison group %s must preserve candidate order" % name)
        payloads = []
        for task in members:
            payloads.append(
                {
                    str(item["id"]): {
                        key: value for key, value in item.items() if key != "gold"
                    }
                    for item in task["candidates"]
                }
            )
        if payloads[0] != payloads[1]:
            raise ValueError(
                "comparison group %s must preserve candidate evidence" % name
            )
        provider_task_ids = {
            str(task.get("provider_task_id") or "") for task in members
        }
        if len(provider_task_ids) != 1 or not next(iter(provider_task_ids)):
            raise ValueError("comparison group %s must share a provider_task_id" % name)

    conditioning_groups = [
        key for key in group_members if key[0] == "task_conditioning_group"
    ]
    if not conditioning_groups:
        raise ValueError("v1K requires a task-conditioning pair")
    for key in conditioning_groups:
        left, right = group_members[key]
        left_roles = {
            str(item["id"]): item["gold"]["repair_role"] for item in left["candidates"]
        }
        right_roles = {
            str(item["id"]): item["gold"]["repair_role"] for item in right["candidates"]
        }
        if not any(
            left_roles[candidate] != right_roles[candidate] for candidate in left_roles
        ):
            raise ValueError(
                "task-conditioning pairs must change at least one gold role"
            )


def _decorate_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    decorated = []
    for source in rows:
        row = dict(source)
        probabilities = [
            float(row["repair_role_probabilities"][role]) for role in REPAIR_ROLES
        ]
        ordered = sorted(probabilities, reverse=True)
        entropy = -sum(
            value * math.log(value) for value in probabilities if value > 0.0
        )
        row["repair_role_margin"] = ordered[0] - ordered[1]
        row["repair_role_entropy"] = entropy / math.log(len(REPAIR_ROLES))
        relevance = float(row["semantic_relevance_probability"])
        role_is_relevant = row["predicted_repair_role"] != "incidental_context"
        row["cross_axis_disagreement"] = (relevance >= 0.5) != role_is_relevant
        decorated.append(row)
    return decorated


def _diagnostics(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    margins = [float(row["repair_role_margin"]) for row in rows]
    entropies = [float(row["repair_role_entropy"]) for row in rows]
    disagreements = [row for row in rows if row["cross_axis_disagreement"]]
    errors = [
        row for row in rows if row["predicted_repair_role"] != row["gold_repair_role"]
    ]
    return {
        "mean_repair_role_margin": sum(margins) / len(margins) if margins else None,
        "mean_repair_role_entropy": (
            sum(entropies) / len(entropies) if entropies else None
        ),
        "low_margin_count": sum(margin < 0.1 for margin in margins),
        "cross_axis_disagreement_count": len(disagreements),
        "cross_axis_disagreement_candidates": [
            str(row["candidate_id"]) for row in disagreements
        ],
        "repair_role_error_count": len(errors),
        "error_mean_margin": (
            sum(float(row["repair_role_margin"]) for row in errors) / len(errors)
            if errors
            else None
        ),
    }


def _rows_by_task(
    task_results: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Mapping[str, Any]]]:
    return {
        str(task["id"]): {str(row["candidate_id"]): row for row in task["candidates"]}
        for task in task_results
    }


def _comparison_metrics(
    spec: Mapping[str, Any], task_results: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    indexed = _rows_by_task(task_results)
    for group_key, output_key in (
        ("task_conditioning_group", "task_conditioning"),
        ("order_invariance_group", "order_invariance"),
        ("relationship_ablation_group", "relationship_ablation"),
    ):
        groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for task in spec["tasks"]:
            if task.get(group_key):
                groups[str(task[group_key])].append(task)
        rows = {}
        for group, tasks in groups.items():
            left, right = tasks
            left_rows = indexed[str(left["id"])]
            right_rows = indexed[str(right["id"])]
            candidate_ids = sorted(set(left_rows) & set(right_rows))
            role_agreement = sum(
                left_rows[item]["predicted_repair_role"]
                == right_rows[item]["predicted_repair_role"]
                for item in candidate_ids
            ) / len(candidate_ids)
            maximum_probability_delta = max(
                abs(
                    float(left_rows[item]["repair_role_probabilities"][role])
                    - float(right_rows[item]["repair_role_probabilities"][role])
                )
                for item in candidate_ids
                for role in REPAIR_ROLES
            )
            maximum_relevance_delta = max(
                abs(
                    float(left_rows[item]["semantic_relevance_probability"])
                    - float(right_rows[item]["semantic_relevance_probability"])
                )
                for item in candidate_ids
            )
            item: Dict[str, Any] = {
                "task_ids": [str(left["id"]), str(right["id"])],
                "candidate_count": len(candidate_ids),
                "predicted_role_agreement": role_agreement,
                "maximum_role_probability_delta": maximum_probability_delta,
                "maximum_relevance_probability_delta": maximum_relevance_delta,
            }
            if group_key == "task_conditioning_group":
                left_gold = {
                    str(candidate["id"]): candidate["gold"]["repair_role"]
                    for candidate in left["candidates"]
                }
                right_gold = {
                    str(candidate["id"]): candidate["gold"]["repair_role"]
                    for candidate in right["candidates"]
                }
                changed = [
                    candidate_id
                    for candidate_id in candidate_ids
                    if left_gold[candidate_id] != right_gold[candidate_id]
                ]
                correct = sum(
                    left_rows[candidate_id]["predicted_repair_role"]
                    == left_gold[candidate_id]
                    for candidate_id in changed
                ) + sum(
                    right_rows[candidate_id]["predicted_repair_role"]
                    == right_gold[candidate_id]
                    for candidate_id in changed
                )
                item["changed_candidate_count"] = len(changed)
                item["changed_candidate_accuracy"] = correct / (2 * len(changed))
            rows[group] = item
        output[output_key] = rows
    return output


def _repetition_stability(
    repetitions: Sequence[Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    if len(repetitions) <= 1:
        return {"repetition_count": len(repetitions), "measured": False}
    indexed_runs = [_rows_by_task(run) for run in repetitions]
    role_agreements = []
    relevance_spans = []
    target_spans = []
    for task_id, candidates in indexed_runs[0].items():
        for candidate_id in candidates:
            rows = [run[task_id][candidate_id] for run in indexed_runs]
            roles = [str(row["predicted_repair_role"]) for row in rows]
            role_agreements.append(Counter(roles).most_common(1)[0][1] / len(roles))
            relevances = [float(row["semantic_relevance_probability"]) for row in rows]
            targets = [
                float(row["repair_role_probabilities"]["implementation_target"])
                for row in rows
            ]
            relevance_spans.append(max(relevances) - min(relevances))
            target_spans.append(max(targets) - min(targets))
    return {
        "repetition_count": len(repetitions),
        "measured": True,
        "mean_modal_role_agreement": sum(role_agreements) / len(role_agreements),
        "maximum_relevance_probability_span": max(relevance_spans),
        "maximum_target_probability_span": max(target_spans),
    }


def run_experiment(
    spec: Mapping[str, Any], provider=None, *, repetitions: int = 1
) -> Dict[str, Any]:
    validate_spec(spec)
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    role_counts = Counter(
        str(candidate["gold"]["repair_role"])
        for task in spec["tasks"]
        for candidate in task["candidates"]
    )
    challenge_counts = Counter(
        tag for task in spec["tasks"] for tag in task.get("challenge_tags") or []
    )
    output: Dict[str, Any] = {
        "schema": V1K_SCHEMA,
        "name": "Repair-role judgment v1K adversarial generalization",
        "task_count": len(spec["tasks"]),
        "candidate_count": sum(len(task["candidates"]) for task in spec["tasks"]),
        "fixture_summary": {
            "repair_role_counts": {role: role_counts[role] for role in REPAIR_ROLES},
            "challenge_counts": dict(sorted(challenge_counts.items())),
            "v1j_prompts_frozen": True,
            "wikonomi_tasks_used": False,
            "language_or_framework_rules": False,
        },
    }
    if provider is None:
        output["status"] = "fixture_validated"
        return output

    started = time.perf_counter()
    usage: Counter = Counter()
    repeated_results: List[List[Dict[str, Any]]] = []
    for _ in range(repetitions):
        task_results = []
        for task in spec["tasks"]:
            provider_task = dict(task)
            provider_task["id"] = str(task.get("provider_task_id") or task["id"])
            raw_rows, judgment, _ = judge_task(provider_task, provider)
            rows = _decorate_rows(raw_rows)
            for key, value in judgment.usage.items():
                if isinstance(value, (int, float)):
                    usage[key] += value
            task_result: Dict[str, Any] = {
                "id": str(task["id"]),
                "candidates": rows,
                "metrics": _classification_metrics(rows),
                "diagnostics": _diagnostics(rows),
                "provider": judgment.provider,
                "model": judgment.model,
            }
            if judgment.request_id:
                task_result["request_id"] = judgment.request_id
            task_results.append(task_result)
        repeated_results.append(task_results)

    first = repeated_results[0]
    all_rows = [row for task in first for row in task["candidates"]]
    task_rows = [(str(task["id"]), task["candidates"]) for task in first]
    output.update(
        {
            "status": "judged",
            "provider_elapsed_seconds": round(time.perf_counter() - started, 6),
            "metrics": _classification_metrics(all_rows),
            "diagnostics": _diagnostics(all_rows),
            "target_ranking": _target_ranking(task_rows),
            "comparisons": _comparison_metrics(spec, first),
            "stability": _repetition_stability(repeated_results),
            "usage": dict(usage),
            "tasks": first,
        }
    )
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run adversarial repair-role judgment v1K fixtures"
    )
    parser.add_argument("--spec", default="experiments/repair_role_v1k.json")
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with Path(args.spec).open("r", encoding="utf-8") as handle:
        spec = json.load(handle)

    provider = JevJudgmentProvider() if args.jev else None
    result = run_experiment(spec, provider, repetitions=args.repetitions)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
