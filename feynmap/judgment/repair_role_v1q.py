"""Repair-role judgment v1Q: non-destructive dual-channel guidance.

v1Q analyzes a judged v1L report offline. Semantic relevance exclusively owns
the context order, while coherent repair-role probabilities provide a separate
edit-target order and explanatory role lanes. No candidate is filtered and no
role prediction can change context retention or ordering.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .repair_role_v1j import REPAIR_ROLES
from .repair_role_v1m import coherent_role_distribution, load_report, validate_report
from .repair_role_v1n import relevance_only_order

V1Q_SCHEMA = "feynmap.repair_role_v1q.v1"


def _coherent_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    coherent = []
    for source in rows:
        row = dict(source)
        probabilities = coherent_role_distribution(row)
        row["coherent_role_probabilities"] = probabilities
        row["coherent_repair_role"] = max(
            REPAIR_ROLES,
            key=lambda role: (probabilities[role], role),
        )
        coherent.append(row)
    return coherent


def _target_order(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    return [
        str(row["candidate_id"])
        for row in sorted(
            rows,
            key=lambda row: (
                -float(row["coherent_role_probabilities"]["implementation_target"]),
                -float(row["semantic_relevance_probability"]),
                str(row["candidate_id"]),
            ),
        )
    ]


def _role_lanes(rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
    lanes = {}
    for role in REPAIR_ROLES:
        selected = [row for row in rows if row["coherent_repair_role"] == role]
        selected.sort(
            key=lambda row: (
                -float(row["coherent_role_probabilities"][role]),
                -float(row["semantic_relevance_probability"]),
                str(row["candidate_id"]),
            )
        )
        lanes[role] = [str(row["candidate_id"]) for row in selected]
    return lanes


def _target_metrics(order: Sequence[str], targets: Sequence[str]) -> Dict[str, float]:
    target_set = set(targets)
    ranks = [
        index + 1
        for index, candidate_id in enumerate(order)
        if candidate_id in target_set
    ]
    first_rank = min(ranks) if ranks else None
    denominator = float(len(target_set)) if target_set else 1.0
    return {
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "recall@1": sum(candidate_id in target_set for candidate_id in order[:1])
        / denominator,
        "recall@3": sum(candidate_id in target_set for candidate_id in order[:3])
        / denominator,
        "task_hit@1": float(bool(order) and order[0] in target_set),
    }


def _average(rows: Sequence[Mapping[str, float]], key: str) -> float:
    return sum(float(row[key]) for row in rows) / float(len(rows)) if rows else 0.0


def analyze_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Build separate context and repair-role channels from judged v1L data."""
    validate_report(report)
    task_results = []
    target_metrics = []
    all_invariant = True
    all_retained = True

    for task in report["tasks"]:
        rows = _coherent_rows(task["candidates"])
        context_order = relevance_only_order(rows)
        target_order = _target_order(rows)
        lanes = _role_lanes(rows)
        reversed_rows = _coherent_rows(list(reversed(task["candidates"])))
        order_invariant = (
            context_order == relevance_only_order(reversed_rows)
            and target_order == _target_order(reversed_rows)
            and lanes == _role_lanes(reversed_rows)
        )
        retained = set(context_order) == {str(row["candidate_id"]) for row in rows}
        targets = [
            str(row["candidate_id"])
            for row in rows
            if str(row["primary_label"]["repair_role"]) == "implementation_target"
        ]
        metrics = _target_metrics(target_order, targets)
        target_metrics.append(metrics)
        all_invariant = all_invariant and order_invariant
        all_retained = all_retained and retained

        annotations = []
        for row in sorted(rows, key=lambda item: str(item["candidate_id"])):
            annotations.append(
                {
                    "candidate_id": str(row["candidate_id"]),
                    "region": dict(row.get("region") or {}),
                    "semantic_relevance_probability": float(
                        row["semantic_relevance_probability"]
                    ),
                    "coherent_repair_role": str(row["coherent_repair_role"]),
                    "coherent_role_probabilities": dict(
                        row["coherent_role_probabilities"]
                    ),
                }
            )

        task_results.append(
            {
                "id": str(task["id"]),
                "context_order": context_order,
                "context_order_owner": "semantic_relevance",
                "retained_candidate_ids": context_order,
                "candidate_retention_ratio": len(context_order) / float(len(rows)),
                "all_candidates_retained": retained,
                "edit_target_order": target_order,
                "role_lanes": lanes,
                "role_annotations": annotations,
                "implementation_target_metrics": metrics,
                "order_invariant": order_invariant,
            }
        )

    return {
        "schema": V1Q_SCHEMA,
        "name": "Repair-role judgment v1Q non-destructive dual-channel guidance",
        "status": "analyzed",
        "source_schema": str(report["schema"]),
        "provider_calls_made": 0,
        "production_policy_changed": False,
        "policy": {
            "context_order_owner": "semantic_relevance_probability",
            "context_filtering_by_role": False,
            "context_reordering_by_role": False,
            "role_output": "separate edit-target order and explanatory lanes",
            "candidate_retention": "all candidates",
            "learned_weights": False,
            "tuned_thresholds": False,
            "language_or_framework_rules": False,
            "gold_labels_used_for_ordering": False,
        },
        "task_count": len(task_results),
        "all_candidates_retained": all_retained,
        "order_invariant": all_invariant,
        "summary": {
            "mean_candidate_retention_ratio": sum(
                float(task["candidate_retention_ratio"]) for task in task_results
            )
            / float(len(task_results)),
            "implementation_target_reciprocal_rank": _average(
                target_metrics, "reciprocal_rank"
            ),
            "implementation_target_recall@1": _average(target_metrics, "recall@1"),
            "implementation_target_recall@3": _average(target_metrics, "recall@3"),
            "implementation_target_task_hit_rate@1": _average(
                target_metrics, "task_hit@1"
            ),
        },
        "tasks": task_results,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze non-destructive dual-channel repair-role guidance"
    )
    parser.add_argument("report", help="Path to a judged v1L JSON report")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = analyze_report(load_report(Path(args.report)))
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
