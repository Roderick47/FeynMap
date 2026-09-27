"""Reproducible S5 benchmark for tool routing and schema delivery."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .context import estimate_tokens
from .grounding import GROUNDING_TOOLS, GROUNDING_TOOL_CONTRACT_VERSION
from .judgment.contracts import JudgmentProvider
from .tool_delivery import DeliveredToolSchema, ToolSchemaPacker
from .tool_routing import AdaptiveToolRouter
from .tool_space import DeterministicToolSelector, ToolCapabilitySpace


BENCHMARK_SCHEMA = "feynmap.tool_routing_benchmark.v1"


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / float(len(values)) if values else None


def _schema_tokens(tools: Sequence[DeliveredToolSchema]) -> int:
    if not tools:
        return 0
    payload = {"tools": [tool.to_dict() for tool in tools]}
    return estimate_tokens(payload)


def validate_dataset(
    dataset: Mapping[str, Any],
    *,
    tool_names: Sequence[str],
) -> None:
    if dataset.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("unsupported tool-routing benchmark schema")
    tasks = dataset.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tool-routing benchmark requires a non-empty tasks list")

    known = set(tool_names)
    task_ids = []
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("each benchmark task must be an object")
        task_id = task.get("id")
        query = task.get("query")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("each benchmark task requires a non-empty id")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("each benchmark task requires a non-empty query")
        task_ids.append(task_id)

        expected = task.get("expected_tools")
        if not isinstance(expected, list):
            raise ValueError("expected_tools must be a list")
        if any(not isinstance(item, str) or not item for item in expected):
            raise ValueError("expected tool names must be non-empty strings")
        if len(expected) != len(set(expected)):
            raise ValueError("expected tool names must be unique within a task")
        unknown = sorted(set(expected) - known)
        if unknown:
            raise ValueError("unknown expected tools: %s" % ", ".join(unknown))

    if len(task_ids) != len(set(task_ids)):
        raise ValueError("benchmark task ids must be unique")
    if not any(task.get("expected_tools") for task in tasks):
        raise ValueError("benchmark requires at least one positive task")
    if not any(not task.get("expected_tools") for task in tasks):
        raise ValueError("benchmark requires at least one unmatched task")


def run_benchmark(
    dataset: Mapping[str, Any],
    provider: Optional[JudgmentProvider] = None,
) -> Dict[str, Any]:
    space = ToolCapabilitySpace.from_contracts(
        GROUNDING_TOOLS,
        namespace="grounding",
        contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
    )
    validate_dataset(dataset, tool_names=tuple(node.name for node in space.nodes))

    settings = dataset.get("settings") or {}
    if not isinstance(settings, Mapping):
        raise ValueError("benchmark settings must be an object")
    limit = int(settings.get("limit", 4))
    max_tools = int(settings.get("max_tools", limit))
    candidate_limit = int(settings.get("candidate_limit", max(2, limit)))
    min_score = float(settings.get("min_score", 0.5))
    min_margin = float(settings.get("min_margin", 0.15))
    if limit < 1:
        raise ValueError("benchmark limit must be positive")

    selector = DeterministicToolSelector(space)
    router = AdaptiveToolRouter(
        space,
        provider=provider,
        min_score=min_score,
        min_margin=min_margin,
        candidate_limit=candidate_limit,
    )
    packer = ToolSchemaPacker(space, max_tools=max_tools)
    full_catalog = tuple(DeliveredToolSchema.from_node(node) for node in space.nodes)
    full_schema_tokens = _schema_tokens(full_catalog)

    rows: List[Dict[str, Any]] = []
    positive_reciprocal_ranks: List[float] = []
    positive_recall_at_1: List[float] = []
    positive_recall_at_limit: List[float] = []
    positive_delivery_recall: List[float] = []
    delivered_token_total = 0
    positive_count = 0
    negative_count = 0
    positive_top1_hits = 0
    negative_abstentions = 0
    successful_tasks = 0

    for task in dataset["tasks"]:
        query = str(task["query"])
        expected_names = tuple(str(item) for item in task["expected_tools"])
        expected_ids = {
            space.node(name).id
            for name in expected_names
            if space.node(name) is not None
        }

        ranked = selector.select(query, limit=len(space.nodes))
        routing = router.route(query, limit=limit)
        packed = packer.pack(routing)
        ranked_ids = [hit.node.id for hit in ranked.hits]
        ranked_names = [hit.node.name for hit in ranked.hits]
        delivered_ids = {tool.tool_id for tool in packed.tools}
        delivered_names = [tool.name for tool in packed.tools]
        delivered_tokens = _schema_tokens(packed.tools)
        delivered_token_total += delivered_tokens

        if expected_ids:
            positive_count += 1
            first_rank = next(
                (index for index, tool_id in enumerate(ranked_ids, 1) if tool_id in expected_ids),
                None,
            )
            top1_correct = bool(ranked_ids and ranked_ids[0] in expected_ids)
            recall_at_1 = (
                float(len(set(ranked_ids[:1]) & expected_ids)) / float(len(expected_ids))
            )
            recall_at_limit = (
                float(len(set(ranked_ids[:limit]) & expected_ids)) / float(len(expected_ids))
            )
            delivery_recall = (
                float(len(delivered_ids & expected_ids)) / float(len(expected_ids))
            )
            reciprocal_rank = (1.0 / float(first_rank)) if first_rank else 0.0
            positive_top1_hits += int(top1_correct)
            positive_reciprocal_ranks.append(reciprocal_rank)
            positive_recall_at_1.append(recall_at_1)
            positive_recall_at_limit.append(recall_at_limit)
            positive_delivery_recall.append(delivery_recall)
            task_success = delivery_recall >= 1.0
            correct_abstention = None
        else:
            negative_count += 1
            top1_correct = None
            recall_at_1 = None
            recall_at_limit = None
            delivery_recall = None
            reciprocal_rank = None
            correct_abstention = not ranked_ids and not delivered_ids
            negative_abstentions += int(correct_abstention)
            task_success = correct_abstention
        successful_tasks += int(task_success)

        rows.append({
            "id": str(task["id"]),
            "query": query,
            "expected_tools": list(expected_names),
            "ranked_tools": ranked_names,
            "delivered_tools": delivered_names,
            "route_sufficient": routing.sufficient,
            "route_reason": routing.reason,
            "provider_called": routing.provider_called,
            "top1_correct": top1_correct,
            "reciprocal_rank": reciprocal_rank,
            "recall@1": recall_at_1,
            "recall@%d" % limit: recall_at_limit,
            "delivery_recall": delivery_recall,
            "correct_abstention": correct_abstention,
            "task_success": task_success,
            "full_schema_tokens": full_schema_tokens,
            "delivered_schema_tokens": delivered_tokens,
            "schema_token_reduction_ratio": (
                float(full_schema_tokens - delivered_tokens) / float(full_schema_tokens)
                if full_schema_tokens else 0.0
            ),
        })

    total_full_tokens = full_schema_tokens * len(rows)
    return {
        "schema": BENCHMARK_SCHEMA,
        "name": str(dataset.get("name", "S5 tool-routing benchmark")),
        "tool_contract_version": GROUNDING_TOOL_CONTRACT_VERSION,
        "tool_count": len(space.nodes),
        "task_count": len(rows),
        "positive_task_count": positive_count,
        "unmatched_task_count": negative_count,
        "settings": {
            "limit": limit,
            "max_tools": max_tools,
            "candidate_limit": candidate_limit,
            "min_score": min_score,
            "min_margin": min_margin,
            "token_estimator": "ceil(canonical_json_characters/4)",
        },
        "tasks": rows,
        "summary": {
            "top1_accuracy": (
                float(positive_top1_hits) / float(positive_count)
                if positive_count else None
            ),
            "mean_reciprocal_rank": _mean(positive_reciprocal_ranks),
            "mean_recall@1": _mean(positive_recall_at_1),
            "mean_recall@%d" % limit: _mean(positive_recall_at_limit),
            "mean_delivery_recall": _mean(positive_delivery_recall),
            "unmatched_accuracy": (
                float(negative_abstentions) / float(negative_count)
                if negative_count else None
            ),
            "task_success_rate": (
                float(successful_tasks) / float(len(rows)) if rows else None
            ),
            "sufficient_route_rate": (
                float(sum(1 for row in rows if row["route_sufficient"])) / float(len(rows))
                if rows else None
            ),
            "provider_call_rate": (
                float(sum(1 for row in rows if row["provider_called"])) / float(len(rows))
                if rows else None
            ),
            "full_catalog_schema_tokens_per_task": full_schema_tokens,
            "total_full_catalog_schema_tokens": total_full_tokens,
            "total_delivered_schema_tokens": delivered_token_total,
            "schema_tokens_avoided": total_full_tokens - delivered_token_total,
            "schema_token_reduction_ratio": (
                float(total_full_tokens - delivered_token_total) / float(total_full_tokens)
                if total_full_tokens else 0.0
            ),
            "mean_delivered_tool_count": (
                sum(len(row["delivered_tools"]) for row in rows) / float(len(rows))
                if rows else 0.0
            ),
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark S5 tool routing and bounded schema delivery.",
    )
    parser.add_argument("dataset", help="Path to a tool-routing benchmark JSON file")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    with Path(args.dataset).open("r", encoding="utf-8") as handle:
        dataset = json.load(handle)
    result = run_benchmark(dataset)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
