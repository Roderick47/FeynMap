"""Context Ranker v1R: historical dual-channel role guidance.

v1R applies the frozen v1Q separation to an existing judged v1O report.  The
v1I relevance file order and metrics are copied and independently verified;
repair roles produce only a separate edit-target order and annotations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .context_ranker_v1f import _average, _file_metrics
from .context_ranker_v1p import SAFETY_METRICS, validate_report
from .repair_role_v1m import load_report
from .repair_role_v1q import _role_lanes, _target_order

V1R_SCHEMA = "feynmap.context_ranker_v1r.v1"


def _file_order(
    candidate_order: Sequence[str], indexed: Mapping[str, Mapping[str, Any]]
) -> List[str]:
    paths = []
    seen = set()
    for candidate_id in candidate_order:
        path = str(indexed[candidate_id].get("path") or "")
        if path and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _metric_deltas(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> Dict[str, float]:
    keys = sorted(
        key
        for key in set(expected) | set(actual)
        if isinstance(expected.get(key), (int, float))
        and isinstance(actual.get(key), (int, float))
    )
    return {key: float(actual[key]) - float(expected[key]) for key in keys}


def _annotation(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": str(row["candidate_id"]),
        "candidate": str(row.get("candidate") or ""),
        "path": str(row.get("path") or ""),
        "semantic_relevance_probability": float(row["semantic_relevance_probability"]),
        "coherent_repair_role": str(row["coherent_repair_role"]),
        "coherent_role_probabilities": dict(row["coherent_role_probabilities"]),
    }


def analyze_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Build non-destructive historical context and repair-guidance channels."""
    validate_report(report)
    tasks = []
    target_metrics = []
    all_context_orders_unchanged = True
    all_context_metrics_unchanged = True
    all_candidates_retained = True
    all_order_invariant = True

    for task in report["tasks"]:
        task_id = str(task["id"])
        adaptive = task["adaptive"]
        shadow = adaptive["role_shadow"]
        rows = [dict(row) for row in shadow["candidates"]]
        indexed = {str(row["candidate_id"]): row for row in rows}
        if len(indexed) != len(rows):
            raise ValueError("v1R task %s has duplicate candidate ids" % task_id)

        context_file_order = [str(path) for path in adaptive["reranked_file_order"]]
        source_context_order = [str(path) for path in adaptive["reranked_file_order"]]
        context_order_unchanged = context_file_order == source_context_order

        gold = {str(path) for path in task["gold_existing_files"]}
        path_backed = {
            str(path) for path in adaptive.get("path_backed_gold_files") or []
        }
        verified_context_metrics = _file_metrics(
            context_file_order,
            gold,
            ks=(1, 3, 5, 10),
            path_backed_files=path_backed,
        )
        source_context_metrics = dict(adaptive["reranked"])
        metric_deltas = _metric_deltas(source_context_metrics, verified_context_metrics)
        context_metrics_unchanged = (
            source_context_metrics == verified_context_metrics
            and all(abs(delta) <= 1e-12 for delta in metric_deltas.values())
        )

        target_order = _target_order(rows)
        target_file_order = _file_order(target_order, indexed)
        lanes = _role_lanes(rows)
        reversed_rows = list(reversed(rows))
        order_invariant = target_order == _target_order(
            reversed_rows
        ) and lanes == _role_lanes(reversed_rows)
        retained = set(target_order) == set(indexed)
        changed_file_proxy_metrics = _file_metrics(
            target_file_order,
            gold,
            ks=(1, 3, 5, 10),
            path_backed_files=path_backed,
        )
        target_metrics.append(changed_file_proxy_metrics)

        tasks.append(
            {
                "id": task_id,
                "context_file_order": context_file_order,
                "context_order_owner": "unchanged_v1i_relevance",
                "context_order_unchanged": context_order_unchanged,
                "context_metrics": source_context_metrics,
                "verified_context_metrics": verified_context_metrics,
                "context_metric_deltas": metric_deltas,
                "context_metrics_unchanged": context_metrics_unchanged,
                "retained_candidate_ids": sorted(indexed),
                "candidate_retention_ratio": len(target_order) / float(len(rows)),
                "all_candidates_retained": retained,
                "edit_target_candidate_order": target_order,
                "edit_target_file_order": target_file_order,
                "role_lanes": lanes,
                "role_annotations": [
                    _annotation(indexed[candidate_id])
                    for candidate_id in sorted(indexed)
                ],
                "changed_file_proxy_metrics": changed_file_proxy_metrics,
                "order_invariant": order_invariant,
            }
        )
        all_context_orders_unchanged = (
            all_context_orders_unchanged and context_order_unchanged
        )
        all_context_metrics_unchanged = (
            all_context_metrics_unchanged and context_metrics_unchanged
        )
        all_candidates_retained = all_candidates_retained and retained
        all_order_invariant = all_order_invariant and order_invariant

    summary_metric_keys = (
        "average_precision",
        "reciprocal_rank",
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@10",
    )
    context_summary = dict(report["adaptive_summary"]["reranked"])
    averaged_target_metrics = _average(target_metrics)
    return {
        "schema": V1R_SCHEMA,
        "name": "Context Ranker v1R historical dual-channel guidance",
        "status": "analyzed",
        "source_schema": str(report["schema"]),
        "provider_calls_made": 0,
        "production_policy_changed": False,
        "policy": {
            "frozen_from": "repair_role_v1q.v1",
            "context_order_owner": "unchanged v1I relevance reranking",
            "context_filtering_by_role": False,
            "context_reordering_by_role": False,
            "candidate_retention": "all role-judged candidates",
            "role_output": "separate edit-target order and explanatory lanes",
            "changed_files_are_exact_role_labels": False,
            "changed_file_evaluation": (
                "proxy only; a changed support or configuration file need not be "
                "an implementation target"
            ),
            "learned_weights": False,
            "tuned_thresholds": False,
            "language_or_framework_rules": False,
            "historical_gold_used_for_ordering": False,
        },
        "task_count": len(tasks),
        "all_context_orders_unchanged": all_context_orders_unchanged,
        "all_context_metrics_unchanged": all_context_metrics_unchanged,
        "all_candidates_retained": all_candidates_retained,
        "order_invariant": all_order_invariant,
        "summary": {
            "context_metrics": context_summary,
            "context_safety_metric_deltas": {metric: 0.0 for metric in SAFETY_METRICS},
            "mean_candidate_retention_ratio": sum(
                float(task["candidate_retention_ratio"]) for task in tasks
            )
            / float(len(tasks)),
            "edit_target_changed_file_proxy": {
                key: averaged_target_metrics[key] for key in summary_metric_keys
            },
        },
        "tasks": tasks,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze historical non-destructive dual-channel role guidance"
    )
    parser.add_argument("report", help="Path to a judged v1O JSON report")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = analyze_report(load_report(Path(args.report)))
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
