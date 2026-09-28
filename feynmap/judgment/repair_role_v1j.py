"""Repair-role judgment v1J over independent synthetic fixtures.

v1J does not change v1I retrieval or its frozen relevance prompt.  It evaluates
whether a bounded judgment provider can distinguish general semantic relevance
from the role a retrieved symbol or source region plays in a repair.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .contracts import JudgmentProvider, JudgmentQuestion, JudgmentResult
from .jev import JevJudgmentProvider

V1J_SCHEMA = "feynmap.repair_role_v1j.v1"
REPAIR_ROLES = (
    "implementation_target",
    "structural_bridge",
    "supporting_context",
    "incidental_context",
)

ROLE_CRITERIA = {
    "implementation_target": (
        "The task requires changing this candidate's behavior or data definition."
    ),
    "structural_bridge": (
        "The candidate connects the task entry point to relevant behavior, but the "
        "fixture gives no reason to edit it."
    ),
    "supporting_context": (
        "The candidate helps explain constraints, expected behavior, or validation, "
        "but is neither the edit target nor merely a path connector."
    ),
    "incidental_context": (
        "The candidate is present because of graph or lexical proximity and does not "
        "materially help complete this repair."
    ),
}

RELEVANCE_PROMPT = (
    "Given only task and grounded_context, what is the probability that candidate "
    "id %r materially helps understand, implement, or validate the requested repair? "
    "A structural connector or behavioral constraint can be relevant even when it "
    "should not be edited. Do not infer that every retrieved candidate is relevant."
)
ROLE_PROMPT = (
    "Given only task and grounded_context, classify candidate id %r by its most "
    "specific repair role. Judge whether its own region must change separately from "
    "whether it lies on a path or provides useful context."
)


def _region_key(candidate: Mapping[str, Any]) -> Tuple[str, int, int]:
    region = candidate.get("region") or {}
    return (
        str(region.get("path") or ""),
        int(region.get("start_line") or 0),
        int(region.get("end_line") or 0),
    )


def validate_spec(spec: Mapping[str, Any]) -> None:
    """Validate the independent fixture corpus and guard against label leakage."""
    if spec.get("schema") != V1J_SCHEMA:
        raise ValueError("unsupported repair-role v1J schema")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1J requires a non-empty tasks list")

    seen_tasks = set()
    observed_roles = set()
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("each v1J task must be an object")
        task_id = str(task.get("id") or "")
        if not task_id or not str(task.get("description") or "").strip():
            raise ValueError("each v1J task requires id and description")
        if task_id in seen_tasks:
            raise ValueError("duplicate v1J task id: %s" % task_id)
        seen_tasks.add(task_id)

        candidates = task.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("v1J task %s requires candidates" % task_id)
        candidate_ids = set()
        regions = set()
        task_roles = set()
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise ValueError("v1J candidates must be objects")
            candidate_id = str(candidate.get("id") or "")
            if not candidate_id or candidate_id in candidate_ids:
                raise ValueError("task %s has missing or duplicate candidate id" % task_id)
            candidate_ids.add(candidate_id)
            region = candidate.get("region")
            if not isinstance(region, Mapping):
                raise ValueError("candidate %s requires a source region" % candidate_id)
            region_key = _region_key(candidate)
            if not region_key[0] or region_key[1] <= 0 or region_key[2] < region_key[1]:
                raise ValueError("candidate %s has an invalid source region" % candidate_id)
            if region_key in regions:
                raise ValueError("task %s has duplicate candidate regions" % task_id)
            regions.add(region_key)

            gold = candidate.get("gold")
            if not isinstance(gold, Mapping):
                raise ValueError("candidate %s requires gold labels" % candidate_id)
            if not isinstance(gold.get("semantic_relevance"), bool):
                raise ValueError("candidate %s requires boolean semantic_relevance" % candidate_id)
            role = str(gold.get("repair_role") or "")
            if role not in REPAIR_ROLES:
                raise ValueError("candidate %s has unknown repair role" % candidate_id)
            if bool(gold["semantic_relevance"]) == (role == "incidental_context"):
                raise ValueError(
                    "candidate %s has inconsistent relevance and repair role" % candidate_id
                )
            task_roles.add(role)
            observed_roles.add(role)

        if task_roles != set(REPAIR_ROLES):
            raise ValueError("task %s must exercise every repair role" % task_id)

        relationships = task.get("relationships") or []
        if not isinstance(relationships, list):
            raise ValueError("task %s relationships must be a list" % task_id)
        for relationship in relationships:
            if not isinstance(relationship, Mapping):
                raise ValueError("v1J relationships must be objects")
            if (
                str(relationship.get("source") or "") not in candidate_ids
                or str(relationship.get("target") or "") not in candidate_ids
                or not str(relationship.get("relationship") or "")
            ):
                raise ValueError("task %s has an invalid relationship" % task_id)

    if observed_roles != set(REPAIR_ROLES):
        raise ValueError("v1J fixture corpus must cover every repair role")


def build_task_state(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Build provider state without exposing fixture labels."""
    candidates = []
    for candidate in task["candidates"]:
        candidates.append(
            {key: value for key, value in candidate.items() if key != "gold"}
        )
    return {
        "task": {
            "id": str(task["id"]),
            "description": str(task["description"]),
        },
        "grounded_context": {
            "candidates": candidates,
            "relationships": [dict(item) for item in task.get("relationships") or []],
            "selection_note": (
                "Candidates are bounded retrieved regions. Presence does not imply "
                "semantic relevance or a need to edit the region."
            ),
        },
    }


def build_questions(task: Mapping[str, Any]) -> Dict[str, JudgmentQuestion]:
    questions: Dict[str, JudgmentQuestion] = {}
    for index, candidate in enumerate(task["candidates"]):
        candidate_id = str(candidate["id"])
        questions["relevance_%d" % index] = JudgmentQuestion.noul(
            RELEVANCE_PROMPT % candidate_id
        )
        questions["role_%d" % index] = JudgmentQuestion.choice(
            ROLE_PROMPT % candidate_id,
            ROLE_CRITERIA,
        )
    return questions


def _bounded_probability(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def _role_probabilities(answer: Any) -> Dict[str, float]:
    probabilities = {
        role: max(0.0, float(answer.probabilities.get(role, 0.0)))
        for role in REPAIR_ROLES
    }
    total = sum(probabilities.values())
    if total <= 0.0:
        chosen = str(answer.value)
        return {role: 1.0 if role == chosen else 0.0 for role in REPAIR_ROLES}
    return {role: value / total for role, value in probabilities.items()}


def judge_task(
    task: Mapping[str, Any], provider: JudgmentProvider
) -> Tuple[List[Dict[str, Any]], JudgmentResult, Dict[str, Any]]:
    state = build_task_state(task)
    result = provider.evaluate(state, build_questions(task))
    rows: List[Dict[str, Any]] = []
    for index, candidate in enumerate(task["candidates"]):
        relevance = _bounded_probability(result.answers["relevance_%d" % index].value)
        role_answer = result.answers["role_%d" % index]
        role = str(role_answer.value)
        if role not in REPAIR_ROLES:
            raise ValueError("provider returned unknown repair role: %s" % role)
        probabilities = _role_probabilities(role_answer)
        gold = candidate["gold"]
        rows.append(
            {
                "candidate_id": str(candidate["id"]),
                "region": dict(candidate["region"]),
                "gold_semantic_relevance": bool(gold["semantic_relevance"]),
                "semantic_relevance_probability": relevance,
                "gold_repair_role": str(gold["repair_role"]),
                "predicted_repair_role": role,
                "repair_role_probabilities": probabilities,
            }
        )
    return rows, result, state


def _safe_log(value: float) -> float:
    return math.log(max(1e-15, min(1.0 - 1e-15, value)))


def _classification_metrics(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    confusion = {
        gold: {predicted: 0 for predicted in REPAIR_ROLES}
        for gold in REPAIR_ROLES
    }
    correct = 0
    relevance_correct = 0
    brier = 0.0
    log_loss = 0.0
    per_role: Dict[str, Dict[str, float]] = {}
    for row in rows:
        gold_role = str(row["gold_repair_role"])
        predicted_role = str(row["predicted_repair_role"])
        confusion[gold_role][predicted_role] += 1
        correct += int(gold_role == predicted_role)
        gold_relevance = 1.0 if row["gold_semantic_relevance"] else 0.0
        probability = float(row["semantic_relevance_probability"])
        relevance_correct += int((probability >= 0.5) == bool(gold_relevance))
        brier += (probability - gold_relevance) ** 2
        log_loss -= gold_relevance * _safe_log(probability)
        log_loss -= (1.0 - gold_relevance) * _safe_log(1.0 - probability)

    f1_values = []
    for role in REPAIR_ROLES:
        true_positive = confusion[role][role]
        false_positive = sum(confusion[gold][role] for gold in REPAIR_ROLES if gold != role)
        false_negative = sum(confusion[role][pred] for pred in REPAIR_ROLES if pred != role)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_role[role] = {"precision": precision, "recall": recall, "f1": f1}
        f1_values.append(f1)

    count = len(rows)
    return {
        "candidate_count": count,
        "semantic_relevance_accuracy": relevance_correct / count if count else None,
        "semantic_relevance_brier": brier / count if count else None,
        "semantic_relevance_log_loss": log_loss / count if count else None,
        "repair_role_accuracy": correct / count if count else None,
        "repair_role_macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "per_role": per_role,
        "confusion_matrix": confusion,
    }


def _target_ranking(task_rows: Sequence[Tuple[str, Sequence[Mapping[str, Any]]]]) -> Dict[str, Any]:
    reciprocal_ranks = []
    recall_at_1 = []
    recall_at_3 = []
    task_orders = {}
    for task_id, rows in task_rows:
        ranked = sorted(
            rows,
            key=lambda row: (
                -float(row["repair_role_probabilities"]["implementation_target"]),
                -float(row["semantic_relevance_probability"]),
                str(row["candidate_id"]),
            ),
        )
        targets = {str(row["candidate_id"]) for row in rows if row["gold_repair_role"] == "implementation_target"}
        order = [str(row["candidate_id"]) for row in ranked]
        task_orders[task_id] = order
        target_ranks = [index for index, candidate_id in enumerate(order, 1) if candidate_id in targets]
        reciprocal_ranks.append(1.0 / min(target_ranks))
        recall_at_1.append(len(targets & set(order[:1])) / len(targets))
        recall_at_3.append(len(targets & set(order[:3])) / len(targets))
    count = len(task_rows)
    return {
        "implementation_target_mrr": sum(reciprocal_ranks) / count if count else None,
        "implementation_target_recall@1": sum(recall_at_1) / count if count else None,
        "implementation_target_recall@3": sum(recall_at_3) / count if count else None,
        "task_orders": task_orders,
    }


def run_experiment(
    spec: Mapping[str, Any], provider: Optional[JudgmentProvider] = None
) -> Dict[str, Any]:
    validate_spec(spec)
    role_counts = Counter(
        str(candidate["gold"]["repair_role"])
        for task in spec["tasks"]
        for candidate in task["candidates"]
    )
    output: Dict[str, Any] = {
        "schema": V1J_SCHEMA,
        "name": "Repair-role judgment v1J on independent synthetic fixtures",
        "task_count": len(spec["tasks"]),
        "candidate_count": sum(len(task["candidates"]) for task in spec["tasks"]),
        "fixture_summary": {
            "repair_role_counts": {role: role_counts[role] for role in REPAIR_ROLES},
            "symbol_or_region_labels": True,
            "wikonomi_tasks_used": False,
            "language_or_framework_rules": False,
        },
    }
    if provider is None:
        output["status"] = "fixture_validated"
        return output

    started = time.perf_counter()
    all_rows: List[Dict[str, Any]] = []
    task_rows: List[Tuple[str, Sequence[Mapping[str, Any]]]] = []
    usage: Counter = Counter()
    results = []
    for task in spec["tasks"]:
        rows, judgment, _ = judge_task(task, provider)
        all_rows.extend(rows)
        task_rows.append((str(task["id"]), rows))
        for key, value in judgment.usage.items():
            if isinstance(value, (int, float)):
                usage[key] += value
        task_result: Dict[str, Any] = {
            "id": str(task["id"]),
            "candidates": rows,
            "metrics": _classification_metrics(rows),
            "provider": judgment.provider,
            "model": judgment.model,
        }
        if judgment.request_id:
            task_result["request_id"] = judgment.request_id
        results.append(task_result)

    output.update(
        {
            "status": "judged",
            "provider_elapsed_seconds": round(time.perf_counter() - started, 6),
            "metrics": _classification_metrics(all_rows),
            "target_ranking": _target_ranking(task_rows),
            "usage": dict(usage),
            "tasks": results,
        }
    )
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run repair-role judgment v1J on independent synthetic fixtures"
    )
    parser.add_argument(
        "--spec",
        default="experiments/repair_role_v1j.json",
        help="Path to a v1J fixture specification",
    )
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--jev", action="store_true", help="Run live Jev judgments")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with Path(args.spec).open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    if args.task:
        selected = set(args.task)
        spec = dict(spec)
        spec["tasks"] = [task for task in spec["tasks"] if task.get("id") in selected]
        missing = selected - {str(task.get("id")) for task in spec["tasks"]}
        if missing:
            raise ValueError("unknown v1J task ids: %s" % ", ".join(sorted(missing)))

    provider = JevJudgmentProvider() if args.jev else None
    result = run_experiment(spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
