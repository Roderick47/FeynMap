"""Context Ranker v1O: frozen role-aware policy on the historical holdout.

v1O preserves v1I retrieval and its relevance-only Jev call.  A second call
uses the frozen v1J role question, then applies the frozen v1N ordering policy
in shadow mode.  Historical changed files are used only for evaluation.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .context_ranker_v1f import (
    _average,
    _candidate_path,
    _file_metrics,
    run_graph_task,
    run_historical_experiment,
)
from .context_ranker_v1i import adaptive_selection_v1i
from .contracts import JudgmentProvider, JudgmentQuestion, JudgmentResult
from .jev import JevJudgmentProvider
from .ranking import baseline_rank
from .repair_role_v1j import (
    REPAIR_ROLES,
    ROLE_CRITERIA,
    ROLE_PROMPT,
    _bounded_probability,
    _role_probabilities,
)
from .repair_role_v1m import coherent_role_distribution
from .repair_role_v1n import role_aware_order

V1O_SCHEMA = "feynmap.context_ranker_v1o.v1"


def _predicted_role(row: Mapping[str, Any]) -> str:
    probabilities = row["coherent_role_probabilities"]
    return max(REPAIR_ROLES, key=lambda role: float(probabilities[role]))


class RoleShadowProvider:
    """Preserve the relevance call and capture a separate role-only judgment."""

    def __init__(self, provider: JudgmentProvider):
        self.provider = provider
        self.name = getattr(provider, "name", provider.__class__.__name__)
        self.captures: List[Dict[str, Any]] = []

    def evaluate(
        self,
        state: Mapping[str, Any],
        questions: Mapping[str, JudgmentQuestion],
    ) -> JudgmentResult:
        relevance_result = self.provider.evaluate(state, questions)
        candidates = list((state.get("grounded_context") or {}).get("candidates") or [])
        baseline = baseline_rank(candidates)
        if len(baseline) != len(questions):
            raise ValueError("v1O relevance questions must cover every candidate")

        role_questions = {
            "role_%d"
            % index: JudgmentQuestion.choice(
                ROLE_PROMPT % item.candidate_id,
                ROLE_CRITERIA,
            )
            for index, item in enumerate(baseline)
        }
        started = time.perf_counter()
        role_result = self.provider.evaluate(state, role_questions)
        role_elapsed = time.perf_counter() - started

        rows = []
        for index, item in enumerate(baseline):
            relevance_answer = relevance_result.answers["candidate_%d" % index]
            role_answer = role_result.answers["role_%d" % index]
            role = str(role_answer.value)
            if role not in REPAIR_ROLES:
                raise ValueError("provider returned unknown repair role: %s" % role)
            row = {
                "candidate_id": item.candidate_id,
                "candidate": dict(item.candidate),
                "semantic_relevance_probability": _bounded_probability(
                    relevance_answer.value
                ),
                "predicted_repair_role": role,
                "repair_role_probabilities": _role_probabilities(role_answer),
            }
            row["coherent_role_probabilities"] = coherent_role_distribution(row)
            rows.append(row)

        self.captures.append(
            {
                "rows": rows,
                "role_usage": dict(role_result.usage),
                "role_model": role_result.model,
                "role_request_id": role_result.request_id,
                "role_elapsed_seconds": round(role_elapsed, 6),
            }
        )
        return relevance_result


def _file_order(
    root_path: Optional[str], rows: Sequence[Mapping[str, Any]]
) -> List[str]:
    order = []
    seen = set()
    if root_path:
        order.append(root_path)
        seen.add(root_path)
    for row in rows:
        path = _candidate_path(row["candidate"])
        if not path or path in seen:
            continue
        order.append(path)
        seen.add(path)
    return order


def _attach_role_shadow(
    task_result: Dict[str, Any], capture: Mapping[str, Any]
) -> None:
    adaptive = task_result["adaptive"]
    rows = [dict(row) for row in capture["rows"]]
    indexed = {str(row["candidate_id"]): row for row in rows}
    order = role_aware_order(rows)
    target_anchor = order[0] if order else None
    eligible = [
        candidate_id
        for candidate_id in order
        if candidate_id == target_anchor
        or _predicted_role(indexed[candidate_id]) != "incidental_context"
    ]
    eligible_rows = [indexed[candidate_id] for candidate_id in eligible]
    root_path = (adaptive.get("baseline_file_order") or [None])[0]
    file_order = _file_order(root_path, eligible_rows)
    gold = set(task_result["gold_existing_files"])
    path_backed = set(adaptive.get("path_backed_gold_files") or [])
    metrics = _file_metrics(
        file_order,
        gold,
        ks=(1, 3, 5, 10),
        path_backed_files=path_backed,
    )

    excluded = [
        candidate_id for candidate_id in order if candidate_id not in set(eligible)
    ]
    changed_file_roles: Dict[str, List[str]] = {}
    candidate_results = []
    for candidate_id in order:
        row = indexed[candidate_id]
        path = _candidate_path(row["candidate"])
        predicted = _predicted_role(row)
        if path in gold:
            changed_file_roles.setdefault(str(path), []).append(predicted)
        candidate_results.append(
            {
                "candidate_id": candidate_id,
                "candidate": str(
                    row["candidate"].get("qualified_name")
                    or row["candidate"].get("name")
                    or candidate_id
                ),
                "path": path,
                "semantic_relevance_probability": row["semantic_relevance_probability"],
                "predicted_repair_role": row["predicted_repair_role"],
                "repair_role_probabilities": dict(row["repair_role_probabilities"]),
                "coherent_repair_role": predicted,
                "coherent_role_probabilities": dict(row["coherent_role_probabilities"]),
                "eligible": candidate_id in set(eligible),
            }
        )

    adaptive["role_shadow"] = {
        "production_policy_changed": False,
        "role_aware_candidate_order": order,
        "eligible_candidate_ids": eligible,
        "excluded_predicted_incidental": excluded,
        "role_aware_file_order": file_order,
        "metrics": metrics,
        "gold_file_role_predictions": changed_file_roles,
        "candidates": candidate_results,
        "usage": dict(capture["role_usage"]),
        "model": capture["role_model"],
        "request_id": capture["role_request_id"],
        "provider_elapsed_seconds": capture["role_elapsed_seconds"],
    }


def _role_summary(tasks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    shadows = [task["adaptive"]["role_shadow"] for task in tasks]
    usage: Counter = Counter()
    elapsed = 0.0
    excluded = 0
    for shadow in shadows:
        elapsed += float(shadow["provider_elapsed_seconds"])
        excluded += len(shadow["excluded_predicted_incidental"])
        for key, value in shadow["usage"].items():
            if isinstance(value, (int, float)):
                usage[key] += value
    return {
        "metrics": _average([shadow["metrics"] for shadow in shadows]),
        "usage": dict(usage),
        "provider_elapsed_seconds": round(elapsed, 6),
        "excluded_predicted_incidental_count": excluded,
    }


def run_graph_task_v1o(
    context,
    task: Mapping[str, Any],
    retrieval_spec: Mapping[str, Any],
    adaptive_spec: Mapping[str, Any],
    provider: JudgmentProvider,
) -> Dict[str, Any]:
    shadow_provider = RoleShadowProvider(provider)
    result = run_graph_task(
        context,
        task,
        retrieval_spec,
        adaptive_spec,
        shadow_provider,
        adaptive_selector=adaptive_selection_v1i,
    )
    if len(shadow_provider.captures) != 1:
        raise ValueError("v1O expected one role capture for a graph task")
    _attach_role_shadow(result, shadow_provider.captures[0])
    return result


def run_experiment(
    repository_path: str,
    spec: Mapping[str, Any],
    provider: Optional[JudgmentProvider] = None,
) -> Dict[str, Any]:
    shadow_provider = RoleShadowProvider(provider) if provider is not None else None
    result = run_historical_experiment(
        repository_path,
        spec,
        shadow_provider,
        adaptive_selector=adaptive_selection_v1i,
    )
    result["schema"] = V1O_SCHEMA
    result["name"] = "Context Ranker v1O - frozen role-policy historical shadow"
    result["shadow_policy"] = {
        "retrieval_frozen_from": "context_ranker_v1i.v1",
        "relevance_call_frozen": True,
        "role_prompt_frozen_from": "repair_role_v1j.v1",
        "coherence_frozen_from": "repair_role_v1m.v1",
        "assembly_frozen_from": "repair_role_v1n.v1",
        "historical_gold_used_for_selection": False,
        "production_policy_changed": False,
        "language_or_framework_rules": False,
    }
    if shadow_provider is None:
        result["status"] = "retrieval_only"
        return result
    if len(shadow_provider.captures) != len(result["tasks"]):
        raise ValueError("v1O role captures do not match historical tasks")
    for task_result, capture in zip(result["tasks"], shadow_provider.captures):
        _attach_role_shadow(task_result, capture)
    result["status"] = "judged"
    result["adaptive_summary"]["role_shadow"] = _role_summary(result["tasks"])
    relevance_usage = Counter(result["adaptive_summary"].get("usage") or {})
    role_usage = Counter(result["adaptive_summary"]["role_shadow"]["usage"])
    result["adaptive_summary"]["combined_usage"] = dict(relevance_usage + role_usage)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run frozen role-aware shadow policy on v1I historical tasks"
    )
    parser.add_argument(
        "repository", help="Local Git checkout of the external repository"
    )
    parser.add_argument("--spec", default="experiments/context_ranker_v1f.json")
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with Path(args.spec).open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    if args.task:
        selected = set(args.task)
        spec = dict(spec)
        spec["tasks"] = [
            task for task in spec["tasks"] if str(task.get("id")) in selected
        ]
        missing = selected - {str(task.get("id")) for task in spec["tasks"]}
        if missing:
            raise ValueError("unknown v1O task ids: %s" % ", ".join(sorted(missing)))

    provider = JevJudgmentProvider() if args.jev else None
    result = run_experiment(args.repository, spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
