"""Repair-role judgment v1M: offline joint-coherence analysis.

v1M does not make provider calls or alter v1J-v1L outputs.  It projects the
independent semantic-relevance and repair-role probabilities from a judged v1L
report onto the four label pairs allowed by the existing role taxonomy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .repair_role_v1j import REPAIR_ROLES
from .repair_role_v1l import V1L_SCHEMA

V1M_SCHEMA = "feynmap.repair_role_v1m.v1"


def _label_key(label: Mapping[str, Any]) -> Tuple[bool, str]:
    return bool(label["semantic_relevance"]), str(label["repair_role"])


def _label_dict(label: Tuple[bool, str]) -> Dict[str, Any]:
    return {"semantic_relevance": label[0], "repair_role": label[1]}


def load_report(path: Path) -> Mapping[str, Any]:
    """Load JSON with the standard library's UTF BOM/encoding detection."""
    with path.open("rb") as handle:
        report = json.load(handle)
    if not isinstance(report, Mapping):
        raise ValueError("v1M report must be a JSON object")
    return report


def validate_report(report: Mapping[str, Any]) -> None:
    """Validate the bounded subset of a judged v1L report required by v1M."""
    if report.get("schema") != V1L_SCHEMA or report.get("status") != "judged":
        raise ValueError("v1M requires a judged repair-role v1L report")
    tasks = report.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1M requires v1L task results")
    for task in tasks:
        if not str(task.get("id") or ""):
            raise ValueError("v1L result task requires an id")
        candidates = task.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("v1L result task requires candidates")
        for row in candidates:
            candidate_id = str(row.get("candidate_id") or "")
            if not candidate_id:
                raise ValueError("v1L result candidate requires an id")
            probability = row.get("semantic_relevance_probability")
            if (
                not isinstance(probability, (int, float))
                or not 0.0 <= probability <= 1.0
            ):
                raise ValueError(
                    "candidate %s has invalid relevance probability" % candidate_id
                )
            probabilities = row.get("repair_role_probabilities")
            if not isinstance(probabilities, Mapping):
                raise ValueError(
                    "candidate %s requires role probabilities" % candidate_id
                )
            values = []
            for role in REPAIR_ROLES:
                value = probabilities.get(role)
                if not isinstance(value, (int, float)) or value < 0.0:
                    raise ValueError(
                        "candidate %s has invalid role probabilities" % candidate_id
                    )
                values.append(float(value))
            if sum(values) <= 0.0:
                raise ValueError(
                    "candidate %s has empty role probabilities" % candidate_id
                )
            if str(row.get("predicted_repair_role") or "") not in REPAIR_ROLES:
                raise ValueError(
                    "candidate %s has invalid predicted role" % candidate_id
                )
            primary = row.get("primary_label")
            acceptable = row.get("acceptable_labels")
            if not isinstance(primary, Mapping):
                raise ValueError("candidate %s requires a primary label" % candidate_id)
            if not isinstance(acceptable, list) or not acceptable:
                raise ValueError(
                    "candidate %s requires acceptable labels" % candidate_id
                )


def coherent_role_distribution(row: Mapping[str, Any]) -> Dict[str, float]:
    """Condition independent answers on the role/relevance taxonomy invariant."""
    relevance = float(row["semantic_relevance_probability"])
    scores = {}
    for role in REPAIR_ROLES:
        role_probability = float(row["repair_role_probabilities"][role])
        agreement_probability = (
            1.0 - relevance if role == "incidental_context" else relevance
        )
        scores[role] = role_probability * agreement_probability
    total = sum(scores.values())
    if total <= 0.0:
        fallback = {
            role: float(row["repair_role_probabilities"][role]) for role in REPAIR_ROLES
        }
        total = sum(fallback.values())
        return {role: fallback[role] / total for role in REPAIR_ROLES}
    return {role: scores[role] / total for role in REPAIR_ROLES}


def _target_ranking(
    tasks: Sequence[Mapping[str, Any]],
    projected: Mapping[Tuple[str, str], Mapping[str, Any]],
) -> Dict[str, Any]:
    reciprocal_ranks = []
    recall_at_1 = []
    recall_at_3 = []
    task_orders = {}
    for task in tasks:
        task_id = str(task["id"])
        rows = task["candidates"]
        ranked = sorted(
            rows,
            key=lambda row: (
                -float(
                    projected[(task_id, str(row["candidate_id"]))][
                        "coherent_role_probabilities"
                    ]["implementation_target"]
                ),
                str(row["candidate_id"]),
            ),
        )
        order = [str(row["candidate_id"]) for row in ranked]
        targets = {
            str(row["candidate_id"])
            for row in rows
            if str(row["primary_label"]["repair_role"]) == "implementation_target"
        }
        if not targets:
            raise ValueError("task %s has no primary implementation target" % task_id)
        target_ranks = [
            index
            for index, candidate_id in enumerate(order, 1)
            if candidate_id in targets
        ]
        reciprocal_ranks.append(1.0 / min(target_ranks))
        recall_at_1.append(len(targets & set(order[:1])) / len(targets))
        recall_at_3.append(len(targets & set(order[:3])) / len(targets))
        task_orders[task_id] = order
    count = len(tasks)
    return {
        "implementation_target_mrr": sum(reciprocal_ranks) / count,
        "implementation_target_recall@1": sum(recall_at_1) / count,
        "implementation_target_recall@3": sum(recall_at_3) / count,
        "task_orders": task_orders,
    }


def run_analysis(report: Mapping[str, Any]) -> Dict[str, Any]:
    validate_report(report)
    rows: List[Dict[str, Any]] = []
    projected = {}
    for task in report["tasks"]:
        task_id = str(task["id"])
        for source in task["candidates"]:
            row = dict(source)
            candidate_id = str(row["candidate_id"])
            relevance = float(row["semantic_relevance_probability"])
            raw_role = str(row["predicted_repair_role"])
            raw_label = (relevance >= 0.5, raw_role)
            raw_axis_consistent = raw_label[0] == (raw_role != "incidental_context")

            coherent = coherent_role_distribution(row)
            coherent_role = max(REPAIR_ROLES, key=lambda role: coherent[role])
            coherent_label = (
                coherent_role != "incidental_context",
                coherent_role,
            )
            consistency_mass = sum(
                float(row["repair_role_probabilities"][role])
                * (1.0 - relevance if role == "incidental_context" else relevance)
                for role in REPAIR_ROLES
            )
            acceptable = {_label_key(label) for label in row["acceptable_labels"]}
            primary = _label_key(row["primary_label"])
            item = {
                "task_id": task_id,
                "candidate_id": candidate_id,
                "region": dict(row["region"]),
                "raw_label": _label_dict(raw_label),
                "raw_axis_consistent": raw_axis_consistent,
                "raw_primary_correct": raw_label == primary,
                "raw_acceptable": raw_label in acceptable,
                "coherent_label": _label_dict(coherent_label),
                "coherent_role_probabilities": coherent,
                "coherent_primary_correct": coherent_label == primary,
                "coherent_acceptable": coherent_label in acceptable,
                "consistency_mass": consistency_mass,
                "role_changed": coherent_role != raw_role,
                "relevance_changed": coherent_label[0] != raw_label[0],
            }
            rows.append(item)
            projected[(task_id, candidate_id)] = item

    count = len(rows)
    cross_axis = [row for row in rows if not row["raw_axis_consistent"]]
    changed = [row for row in rows if row["role_changed"] or row["relevance_changed"]]
    repairs = [
        row for row in rows if not row["raw_acceptable"] and row["coherent_acceptable"]
    ]
    regressions = [
        row for row in rows if row["raw_acceptable"] and not row["coherent_acceptable"]
    ]
    return {
        "schema": V1M_SCHEMA,
        "name": "Repair-role judgment v1M joint-coherence analysis",
        "status": "analyzed",
        "source_schema": str(report["schema"]),
        "provider_calls_made": 0,
        "task_count": len(report["tasks"]),
        "candidate_count": count,
        "metrics": {
            "raw_primary_joint_accuracy": sum(
                row["raw_primary_correct"] for row in rows
            )
            / count,
            "coherent_primary_joint_accuracy": sum(
                row["coherent_primary_correct"] for row in rows
            )
            / count,
            "raw_acceptable_joint_accuracy": sum(row["raw_acceptable"] for row in rows)
            / count,
            "coherent_acceptable_joint_accuracy": sum(
                row["coherent_acceptable"] for row in rows
            )
            / count,
            "cross_axis_disagreement_count": len(cross_axis),
            "coherent_role_changed_count": sum(row["role_changed"] for row in rows),
            "coherent_relevance_changed_count": sum(
                row["relevance_changed"] for row in rows
            ),
            "repaired_unacceptable_count": len(repairs),
            "introduced_regression_count": len(regressions),
            "mean_consistency_mass": sum(row["consistency_mass"] for row in rows)
            / count,
            "minimum_consistency_mass": min(row["consistency_mass"] for row in rows),
        },
        "target_ranking": _target_ranking(report["tasks"], projected),
        "coherence_cases": changed,
        "remaining_unacceptable_cases": [
            row for row in rows if not row["coherent_acceptable"]
        ],
        "introduced_regressions": regressions,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze joint coherence in a judged repair-role v1L report"
    )
    parser.add_argument("report", help="Path to a judged v1L JSON report")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    report = load_report(Path(args.report))
    result = run_analysis(report)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
