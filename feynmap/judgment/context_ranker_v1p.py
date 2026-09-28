"""Context Ranker v1P: offline promotion gate for v1O holdout evidence.

v1P makes no provider calls and changes no ranking policy.  It compares the
frozen relevance-only and role-shadow results already recorded by v1O, using
predeclared non-regression checks rather than learning weights or thresholds
from the historical tasks.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .context_ranker_v1o import V1O_SCHEMA
from .repair_role_v1m import load_report

V1P_SCHEMA = "feynmap.context_ranker_v1p.v1"
SAFETY_METRICS = (
    "average_precision",
    "reciprocal_rank",
    "recall@1",
    "recall@3",
    "recall@5",
    "recall@10",
)


def _files(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})


def _number(mapping: Mapping[str, Any], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError("v1P requires numeric metric %s" % key)
    return float(value)


def _ratio(numerator: Any, denominator: Any) -> Optional[float]:
    if not isinstance(numerator, (int, float)):
        return None
    if not isinstance(denominator, (int, float)) or float(denominator) == 0.0:
        return None
    return float(numerator) / float(denominator)


def validate_report(report: Mapping[str, Any]) -> None:
    if report.get("schema") != V1O_SCHEMA or report.get("status") != "judged":
        raise ValueError("v1P requires a judged context-ranker v1O report")
    tasks = report.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1P requires v1O task results")
    for task in tasks:
        task_id = str(task.get("id") or "")
        adaptive = task.get("adaptive")
        if not task_id or not isinstance(adaptive, Mapping):
            raise ValueError("v1P task requires an id and adaptive result")
        relevance = adaptive.get("reranked")
        shadow = adaptive.get("role_shadow")
        if not isinstance(relevance, Mapping) or not isinstance(shadow, Mapping):
            raise ValueError("v1P task %s requires both policies" % task_id)
        role_metrics = shadow.get("metrics")
        if not isinstance(role_metrics, Mapping):
            raise ValueError("v1P task %s requires role-shadow metrics" % task_id)
        for metric in SAFETY_METRICS:
            _number(relevance, metric)
            _number(role_metrics, metric)
        if not isinstance(shadow.get("candidates"), list):
            raise ValueError("v1P task %s requires role candidates" % task_id)


def _usage_analysis(summary: Mapping[str, Any]) -> Dict[str, Any]:
    relevance = summary.get("usage") or {}
    role_summary = summary.get("role_shadow") or {}
    role = role_summary.get("usage") or {}
    combined = summary.get("combined_usage") or {}
    keys = sorted(set(relevance) | set(role) | set(combined))
    ratios = {}
    for key in keys:
        ratios[key] = {
            "role_to_relevance": _ratio(role.get(key), relevance.get(key)),
            "combined_to_relevance": _ratio(combined.get(key), relevance.get(key)),
        }
    return {
        "relevance": dict(relevance),
        "role": dict(role),
        "combined": dict(combined),
        "ratios": ratios,
        "role_elapsed_to_relevance": _ratio(
            role_summary.get("provider_elapsed_seconds"),
            summary.get("provider_elapsed_seconds"),
        ),
    }


def analyze_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply conservative, threshold-free promotion checks to v1O output."""
    validate_report(report)
    task_results = []
    aggregate_regressions = []
    new_missing_all = set()
    excluded_changed_all = []

    for task in report["tasks"]:
        task_id = str(task["id"])
        relevance = task["adaptive"]["reranked"]
        shadow = task["adaptive"]["role_shadow"]
        role_metrics = shadow["metrics"]
        deltas = {
            metric: _number(role_metrics, metric) - _number(relevance, metric)
            for metric in SAFETY_METRICS
        }
        regressions = [metric for metric, delta in deltas.items() if delta < -1e-12]
        relevance_missing = set(_files(relevance.get("missing_gold_files")))
        role_missing = set(_files(role_metrics.get("missing_gold_files")))
        new_missing = sorted(role_missing - relevance_missing)
        recovered = sorted(relevance_missing - role_missing)
        new_missing_all.update(new_missing)

        gold = set(_files(task.get("gold_existing_files")))
        excluded_changed = []
        for row in shadow["candidates"]:
            path = str(row.get("path") or "")
            if path not in gold or bool(row.get("eligible")):
                continue
            diagnostic = {
                "task_id": task_id,
                "path": path,
                "candidate_id": str(row.get("candidate_id") or ""),
                "candidate": str(row.get("candidate") or ""),
                "semantic_relevance_probability": row.get(
                    "semantic_relevance_probability"
                ),
                "predicted_repair_role": row.get("predicted_repair_role"),
                "coherent_repair_role": row.get("coherent_repair_role"),
                "coherent_role_probabilities": dict(
                    row.get("coherent_role_probabilities") or {}
                ),
            }
            excluded_changed.append(diagnostic)
            excluded_changed_all.append(diagnostic)

        safe = not regressions and not new_missing
        task_results.append(
            {
                "id": task_id,
                "promotion_safe": safe,
                "metric_deltas": deltas,
                "regressed_metrics": regressions,
                "new_missing_gold_files": new_missing,
                "recovered_gold_files": recovered,
                "excluded_changed_file_candidates": excluded_changed,
            }
        )

    relevance_summary = report["adaptive_summary"]["reranked"]
    role_summary = report["adaptive_summary"]["role_shadow"]["metrics"]
    aggregate_deltas = {}
    for metric in SAFETY_METRICS:
        delta = _number(role_summary, metric) - _number(relevance_summary, metric)
        aggregate_deltas[metric] = delta
        if delta < -1e-12:
            aggregate_regressions.append(metric)

    unsafe_tasks = [row["id"] for row in task_results if not row["promotion_safe"]]
    promotion_ready = not aggregate_regressions and not unsafe_tasks
    return {
        "schema": V1P_SCHEMA,
        "name": "Context Ranker v1P - historical holdout promotion gate",
        "status": "analyzed",
        "source_schema": str(report["schema"]),
        "provider_calls_made": 0,
        "production_policy_changed": False,
        "policy": {
            "learned_weights": False,
            "tuned_thresholds": False,
            "historical_gold_used_for_ranking": False,
            "gate": (
                "no aggregate or per-task regression in declared safety metrics "
                "and no newly missing existing changed file"
            ),
            "safety_metrics": list(SAFETY_METRICS),
        },
        "promotion_ready": promotion_ready,
        "decision": (
            "eligible_for_explicit_review"
            if promotion_ready
            else "reject_hard_incidental_filter"
        ),
        "recommendation": (
            "Retain role output as shadow evidence; do not promote "
            "incidental-role filtering."
            if not promotion_ready
            else "All automatic safety gates passed; explicit review is still required."
        ),
        "summary": {
            "task_count": len(task_results),
            "safe_task_count": len(task_results) - len(unsafe_tasks),
            "regressed_task_count": len(unsafe_tasks),
            "regressed_tasks": unsafe_tasks,
            "aggregate_metric_deltas": aggregate_deltas,
            "aggregate_regressed_metrics": aggregate_regressions,
            "new_missing_gold_files": sorted(new_missing_all),
            "excluded_changed_file_candidate_count": len(excluded_changed_all),
            "excluded_changed_file_candidates": excluded_changed_all,
            "usage": _usage_analysis(report["adaptive_summary"]),
        },
        "tasks": task_results,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply the offline v1P promotion gate to a judged v1O report"
    )
    parser.add_argument("report", help="Path to a judged v1O JSON report")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = analyze_report(load_report(Path(args.report)))
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
