"""Repair-role judgment v1N: token-budgeted shadow context assembly.

v1N consumes a judged v1L report and its independent fixture corpus.  It makes
no provider calls and does not change v1I.  The experiment compares a
deterministic role-aware context order with relevance-only ordering under
several relative token budgets.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..context import estimate_tokens
from .repair_role_v1j import REPAIR_ROLES
from .repair_role_v1l import V1L_SCHEMA
from .repair_role_v1m import coherent_role_distribution, load_report

V1N_SCHEMA = "feynmap.repair_role_v1n.v1"
DEFAULT_SPEC = "experiments/repair_role_v1n.json"
DEFAULT_FIXTURE = "experiments/repair_role_v1l.json"


def validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != V1N_SCHEMA:
        raise ValueError("unsupported repair-role v1N schema")
    fractions = spec.get("budget_fractions")
    if not isinstance(fractions, list) or not fractions:
        raise ValueError("v1N requires budget_fractions")
    if any(
        not isinstance(value, (int, float)) or not 0.0 < float(value) <= 1.0
        for value in fractions
    ):
        raise ValueError("v1N budget fractions must be in (0, 1]")
    if len({float(value) for value in fractions}) != len(fractions):
        raise ValueError("v1N budget fractions must be unique")
    if list(map(float, fractions)) != sorted(map(float, fractions)):
        raise ValueError("v1N budget fractions must be sorted")


def _candidate_payload(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if key not in {"adjudication", "gold"}
    }


def _predicted_role(candidate: Mapping[str, Any]) -> str:
    probabilities = candidate["coherent_role_probabilities"]
    return max(REPAIR_ROLES, key=lambda role: float(probabilities[role]))


def role_aware_order(candidates: Sequence[Mapping[str, Any]]) -> List[str]:
    """Order candidates by target safety, role diversity, then relevance."""
    if not candidates:
        return []
    indexed = {str(row["candidate_id"]): row for row in candidates}
    if len(indexed) != len(candidates):
        raise ValueError("role-aware candidates require unique ids")

    def probability(candidate_id: str, role: str) -> float:
        return float(indexed[candidate_id]["coherent_role_probabilities"][role])

    candidate_ids = sorted(indexed)
    target_anchor = min(
        candidate_ids,
        key=lambda candidate_id: (
            -probability(candidate_id, "implementation_target"),
            candidate_id,
        ),
    )
    order = [target_anchor]
    selected = {target_anchor}

    predicted_targets = sorted(
        (
            candidate_id
            for candidate_id in candidate_ids
            if candidate_id not in selected
            and _predicted_role(indexed[candidate_id]) == "implementation_target"
        ),
        key=lambda candidate_id: (
            -probability(candidate_id, "implementation_target"),
            candidate_id,
        ),
    )
    order.extend(predicted_targets)
    selected.update(predicted_targets)

    # Reserve one early position for each useful non-target role when present.
    for role in ("supporting_context", "structural_bridge"):
        matching = [
            candidate_id
            for candidate_id in candidate_ids
            if candidate_id not in selected
            and _predicted_role(indexed[candidate_id]) == role
        ]
        if matching:
            anchor = min(
                matching,
                key=lambda candidate_id: (
                    -probability(candidate_id, role),
                    candidate_id,
                ),
            )
            order.append(anchor)
            selected.add(anchor)

    remaining = [
        candidate_id for candidate_id in candidate_ids if candidate_id not in selected
    ]
    remaining.sort(
        key=lambda candidate_id: (
            -(1.0 - probability(candidate_id, "incidental_context")),
            -max(
                probability(candidate_id, role)
                for role in REPAIR_ROLES
                if role != "incidental_context"
            ),
            candidate_id,
        )
    )
    order.extend(remaining)
    return order


def relevance_only_order(candidates: Sequence[Mapping[str, Any]]) -> List[str]:
    return [
        str(row["candidate_id"])
        for row in sorted(
            candidates,
            key=lambda row: (
                -float(row["semantic_relevance_probability"]),
                str(row["candidate_id"]),
            ),
        )
    ]


def assemble_under_budget(
    order: Sequence[str],
    costs: Mapping[str, int],
    max_tokens: int,
    *,
    eligible_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    selected = []
    used = 0
    eligible = set(eligible_ids) if eligible_ids is not None else set(order)
    for candidate_id in order:
        if candidate_id not in eligible:
            continue
        cost = int(costs[candidate_id])
        if cost <= max_tokens - used:
            selected.append(candidate_id)
            used += cost
    return {
        "selected": selected,
        "used_tokens": used,
        "max_tokens": max_tokens,
        "remaining_tokens": max_tokens - used,
        "utilization": used / max_tokens,
    }


def _selection_metrics(
    selection: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    selected = set(selection["selected"])
    targets = {
        candidate_id
        for candidate_id, row in rows.items()
        if str(row["primary_label"]["repair_role"]) == "implementation_target"
    }
    relevant = {
        candidate_id
        for candidate_id, row in rows.items()
        if bool(row["primary_label"]["semantic_relevance"])
    }
    incidental = {
        candidate_id
        for candidate_id, row in rows.items()
        if str(row["primary_label"]["repair_role"]) == "incidental_context"
    }
    acceptable_relevant = {
        candidate_id
        for candidate_id, row in rows.items()
        if any(bool(label["semantic_relevance"]) for label in row["acceptable_labels"])
    }
    unambiguous_incidental = set(rows) - acceptable_relevant
    available_context_roles = {
        str(row["primary_label"]["repair_role"])
        for row in rows.values()
        if str(row["primary_label"]["repair_role"])
        in {"supporting_context", "structural_bridge"}
    }
    selected_context_roles = {
        str(rows[candidate_id]["primary_label"]["repair_role"])
        for candidate_id in selected
        if str(rows[candidate_id]["primary_label"]["repair_role"])
        in available_context_roles
    }
    selected_acceptable_context_roles = {
        str(label["repair_role"])
        for candidate_id in selected
        for label in rows[candidate_id]["acceptable_labels"]
        if str(label["repair_role"]) in available_context_roles
    }
    count = len(selected)
    return {
        **dict(selection),
        "selected_count": count,
        "implementation_target_hit": bool(selected & targets),
        "implementation_target_recall": (
            len(selected & targets) / len(targets) if targets else None
        ),
        "semantic_relevance_recall": (
            len(selected & relevant) / len(relevant) if relevant else None
        ),
        "acceptable_semantic_relevance_recall": (
            len(selected & acceptable_relevant) / len(acceptable_relevant)
            if acceptable_relevant
            else None
        ),
        "context_role_coverage": (
            len(selected_context_roles) / len(available_context_roles)
            if available_context_roles
            else 1.0
        ),
        "acceptable_context_role_coverage": (
            len(selected_acceptable_context_roles) / len(available_context_roles)
            if available_context_roles
            else 1.0
        ),
        "incidental_selection_ratio": (
            len(selected & incidental) / count if count else 0.0
        ),
        "unacceptable_selection_ratio": (
            len(selected & unambiguous_incidental) / count if count else 0.0
        ),
    }


def _average(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def _load_fixture(path: Path) -> Mapping[str, Any]:
    with path.open("rb") as handle:
        fixture = json.load(handle)
    if not isinstance(fixture, Mapping) or fixture.get("schema") != V1L_SCHEMA:
        raise ValueError("v1N requires a repair-role v1L fixture")
    return fixture


def run_experiment(
    report: Mapping[str, Any],
    fixture: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> Dict[str, Any]:
    validate_spec(spec)
    if report.get("schema") != V1L_SCHEMA or report.get("status") != "judged":
        raise ValueError("v1N requires a judged repair-role v1L report")

    fixture_tasks = {str(task["id"]): task for task in fixture.get("tasks") or []}
    report_tasks = {str(task["id"]): task for task in report.get("tasks") or []}
    if set(fixture_tasks) != set(report_tasks):
        raise ValueError("v1N fixture and report task ids must match")

    task_results = []
    summary_rows: Dict[str, Dict[str, List[Mapping[str, Any]]]] = {}
    all_order_invariant = True
    for task_id in sorted(report_tasks):
        fixture_task = fixture_tasks[task_id]
        report_task = report_tasks[task_id]
        fixture_candidates = {
            str(candidate["id"]): candidate
            for candidate in fixture_task.get("candidates") or []
        }
        report_rows = {
            str(row["candidate_id"]): row for row in report_task.get("candidates") or []
        }
        if set(fixture_candidates) != set(report_rows):
            raise ValueError("task %s candidate ids must match" % task_id)

        costs = {
            candidate_id: max(
                1, estimate_tokens(_candidate_payload(fixture_candidates[candidate_id]))
            )
            for candidate_id in fixture_candidates
        }
        candidates = []
        for candidate_id, source in report_rows.items():
            row = dict(source)
            row["coherent_role_probabilities"] = coherent_role_distribution(row)
            candidates.append(row)
        candidates_by_id = {str(row["candidate_id"]): row for row in candidates}

        role_order = role_aware_order(candidates)
        relevance_order = relevance_only_order(candidates)
        reversed_order = role_aware_order(list(reversed(candidates)))
        order_invariant = role_order == reversed_order
        all_order_invariant = all_order_invariant and order_invariant
        strongest_target = role_order[0]
        role_eligible = [
            candidate_id
            for candidate_id in role_order
            if candidate_id == strongest_target
            or _predicted_role(candidates_by_id[candidate_id]) != "incidental_context"
        ]
        relevance_eligible = [
            str(row["candidate_id"])
            for row in candidates
            if float(row["semantic_relevance_probability"]) >= 0.5
        ]
        minimum_anchor_tokens = costs[strongest_target]
        total_tokens = sum(costs.values())

        budgets = []
        for fraction_value in spec["budget_fractions"]:
            fraction = float(fraction_value)
            max_tokens = max(
                minimum_anchor_tokens,
                int(math.ceil(total_tokens * fraction)),
            )
            budget_key = "fraction_%g" % fraction
            role_selection = _selection_metrics(
                assemble_under_budget(
                    role_order,
                    costs,
                    max_tokens,
                    eligible_ids=role_eligible,
                ),
                report_rows,
            )
            relevance_selection = _selection_metrics(
                assemble_under_budget(
                    relevance_order,
                    costs,
                    max_tokens,
                    eligible_ids=relevance_eligible,
                ),
                report_rows,
            )
            budgets.append(
                {
                    "budget_key": budget_key,
                    "budget_fraction": fraction,
                    "max_tokens": max_tokens,
                    "role_aware": role_selection,
                    "relevance_only": relevance_selection,
                }
            )
            summary = summary_rows.setdefault(
                budget_key, {"role_aware": [], "relevance_only": []}
            )
            summary["role_aware"].append(role_selection)
            summary["relevance_only"].append(relevance_selection)

        task_results.append(
            {
                "id": task_id,
                "candidate_token_costs": dict(sorted(costs.items())),
                "total_candidate_tokens": total_tokens,
                "minimum_target_anchor_tokens": minimum_anchor_tokens,
                "role_aware_order": role_order,
                "relevance_only_order": relevance_order,
                "role_aware_eligible": role_eligible,
                "relevance_only_eligible": relevance_eligible,
                "order_invariant": order_invariant,
                "budgets": budgets,
            }
        )

    summary = {}
    metric_keys = (
        "implementation_target_recall",
        "semantic_relevance_recall",
        "acceptable_semantic_relevance_recall",
        "context_role_coverage",
        "acceptable_context_role_coverage",
        "incidental_selection_ratio",
        "unacceptable_selection_ratio",
        "selected_count",
        "utilization",
    )
    for budget_key, policies in summary_rows.items():
        item = {}
        for policy, rows in policies.items():
            item[policy] = {key: _average(rows, key) for key in metric_keys}
            item[policy]["implementation_target_task_hit_rate"] = _average(
                rows, "implementation_target_hit"
            )
        item["role_aware_target_recall_delta"] = (
            item["role_aware"]["implementation_target_recall"]
            - item["relevance_only"]["implementation_target_recall"]
        )
        item["role_aware_context_coverage_delta"] = (
            item["role_aware"]["context_role_coverage"]
            - item["relevance_only"]["context_role_coverage"]
        )
        item["role_aware_acceptable_context_coverage_delta"] = (
            item["role_aware"]["acceptable_context_role_coverage"]
            - item["relevance_only"]["acceptable_context_role_coverage"]
        )
        summary[budget_key] = item

    return {
        "schema": V1N_SCHEMA,
        "name": "Repair-role judgment v1N token-budgeted shadow assembly",
        "status": "analyzed",
        "provider_calls_made": 0,
        "production_policy_changed": False,
        "source_schema": str(report["schema"]),
        "task_count": len(task_results),
        "budget_fractions": [float(value) for value in spec["budget_fractions"]],
        "policy": {
            "target_anchor": "highest coherent implementation-target probability",
            "role_diversity": "one supporting-context and one structural-bridge anchor",
            "remainder": "coherent non-incidental probability",
            "budget_backfill": "predicted incidental candidates are ineligible",
            "gold_labels_used_for_selection": False,
            "language_or_framework_rules": False,
        },
        "order_invariant": all_order_invariant,
        "summary": summary,
        "tasks": task_results,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run token-budgeted repair-role shadow context assembly"
    )
    parser.add_argument("report", help="Path to a judged v1L JSON report")
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument("--spec", default=DEFAULT_SPEC)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    report = load_report(Path(args.report))
    fixture = _load_fixture(Path(args.fixture))
    with Path(args.spec).open("rb") as handle:
        spec = json.load(handle)
    result = run_experiment(report, fixture, spec)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
