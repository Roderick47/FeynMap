"""P2.4 development replay over the already-seen P2.3b fulfillment corpus.

This is intentionally a regression diagnostic, not a held-out accuracy score.
It checks that the body-level facts missing in P2.3b are representable inside a
bounded task-conditioned evidence packet without changing semantic graph truth.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .behavioral_context import BehaviorEvidenceBudget
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .p2_3b_fidelity import load_manifest
from .task_evidence import TaskConditionedEvidencePipeline


DEV_PATTERNS = {
    "reserve-order-implementation": [
        "ensure_stock",
        "item.quantity -= requested_quantity",
        "return reservation_message",
    ],
    "reservation-regression-test": [
        "requested_quantity > item.quantity",
        "InsufficientStock",
        "item.quantity == 2",
    ],
    "priority-migration-answer": [
        '"priority" not in row',
        'row["priority"] = priority_default()',
        'return "normal"',
    ],
    "cancel-policy-answer": [
        "return can_cancel(status)",
        'status in {"queued", "packed"}',
    ],
    "javascript-status-answer": [
        "normalizeStatus",
        ".trim().toUpperCase()",
        "SHIPMENT:",
    ],
}


def _standard_budget(manifest: Mapping[str, Any]) -> MinimalContextBudget:
    row = next(item for item in manifest["budgets"] if item["id"] == "standard")
    return MinimalContextBudget(
        max_tokens=int(row["max_tokens"]),
        max_nodes=int(row["max_nodes"]),
        max_edges=int(row["max_edges"]),
    )


def _packet_text(payload: Mapping[str, Any]) -> str:
    behavior = payload.get("behavioral_evidence", {})
    return json.dumps(behavior, sort_keys=True, ensure_ascii=False)


def run_replay(
    manifest_path: Path,
    project_root: Path,
    *,
    behavior_budget: BehaviorEvidenceBudget,
) -> Dict[str, Any]:
    manifest = load_manifest(manifest_path)
    graph = FeynMapEngine().analyze(
        str(project_root),
        language=manifest["source"]["language"],
        framework=manifest["source"]["framework"],
    )
    if graph.diagnostics.get("errors"):
        raise ValueError("P2.4 development graph errors: %r" % graph.diagnostics["errors"][:3])
    pipeline = TaskConditionedEvidencePipeline(
        graph,
        project_root,
        behavior_budget=behavior_budget,
    )
    context_budget = _standard_budget(manifest)
    activation = manifest["activation"]
    records = []

    for task in manifest["tasks"]:
        result = pipeline.concept(
            task["query"],
            context_budget=context_budget,
            behavior_budget=behavior_budget,
            seed_limit=int(activation["seed_limit"]),
            candidate_limit=int(activation["candidate_limit"]),
            max_depth=int(activation["max_depth"]),
            beam_width=int(activation["beam_width"]),
            max_nodes=int(activation["max_nodes"]),
            direction=str(activation["direction"]),
        )
        text = _packet_text(result.payload)
        patterns = DEV_PATTERNS.get(task["id"], [])
        pattern_results = {pattern: pattern in text for pattern in patterns}
        missing_control_ok = True
        if task["id"] == "missing-refund-identifier":
            missing_control_ok = (
                list(result.sparse.context.unresolved_query_identifiers) == ["issue_refund"]
                and "issue_refund" not in " ".join(
                    item.summary for item in result.behavioral.delivered_observations
                )
                and not result.sufficient
            )
        record = {
            "task_id": task["id"],
            "query": task["query"],
            "base_context_tokens": result.sparse.context.delivered_tokens,
            "behavior_tokens": result.behavioral.behavior_tokens,
            "combined_tokens": result.behavioral.total_tokens,
            "candidate_observations": result.behavioral.candidate_observations,
            "delivered_observations": len(result.behavioral.delivered_observations),
            "omitted_relevant": result.behavioral.omitted_relevant_observations,
            "omitted_critical": result.behavioral.omitted_critical_observations,
            "sufficient": result.sufficient,
            "unresolved_query_identifiers": list(
                result.sparse.context.unresolved_query_identifiers
            ),
            "known_development_patterns": pattern_results,
            "known_patterns_present": all(pattern_results.values()),
            "missing_identifier_control_ok": missing_control_ok,
        }
        if result.behavioral.behavior_tokens > behavior_budget.max_tokens:
            raise ValueError(task["id"] + ": behavioral budget exceeded")
        records.append(record)

    answerable = [row for row in records if row["task_id"] != "missing-refund-identifier"]
    missing = next(row for row in records if row["task_id"] == "missing-refund-identifier")
    return {
        "schema": "feynmap.p2_4_development_replay.v1",
        "status": "development_regression_only_not_held_out",
        "source_manifest_git_blob": "d136168b47939af7ce8f9440cc9abd022b777310",
        "task_count": len(records),
        "behavior_budget": {
            "max_tokens": behavior_budget.max_tokens,
            "max_observations": behavior_budget.max_observations,
            "max_source_chars": behavior_budget.max_source_chars,
        },
        "answerable_known_pattern_tasks_passing": sum(
            row["known_patterns_present"] for row in answerable
        ),
        "answerable_known_pattern_tasks": len(answerable),
        "missing_identifier_control_ok": missing["missing_identifier_control_ok"],
        "mean_behavior_tokens": round(
            sum(row["behavior_tokens"] for row in records) / len(records), 2
        ),
        "mean_combined_tokens": round(
            sum(row["combined_tokens"] for row in records) / len(records), 2
        ),
        "records": records,
        "limitations": [
            "The P2.3b fulfillment fixture and expected development patterns were already inspected while implementing P2.4.",
            "This replay measures representation/regression coverage, not downstream model-answer correctness.",
            "The deterministic token estimate remains compact-JSON ceil(chars/4), not a provider tokenizer.",
            "A fresh P2.4 corpus must be frozen before any new shipping/default decision.",
        ],
    }


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="experiments/p2_3b_answer_manifest.json")
    parser.add_argument("--project-root", default="experiments/fixtures/p2_3b_fulfillment")
    parser.add_argument("--output")
    parser.add_argument("--behavior-tokens", type=int, default=2200)
    args = parser.parse_args(argv)
    result = run_replay(
        Path(args.manifest),
        Path(args.project_root).resolve(),
        behavior_budget=BehaviorEvidenceBudget(
            max_tokens=args.behavior_tokens,
            max_observations=48,
            max_source_chars=5000,
        ),
    )
    if args.output:
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "status": result["status"],
        "answerable_known_pattern_tasks_passing": result["answerable_known_pattern_tasks_passing"],
        "answerable_known_pattern_tasks": result["answerable_known_pattern_tasks"],
        "missing_identifier_control_ok": result["missing_identifier_control_ok"],
        "mean_behavior_tokens": result["mean_behavior_tokens"],
        "mean_combined_tokens": result["mean_combined_tokens"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
