"""Benchmark S4 bounded active state across multi-step agent/tool loops."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .active_state import ActiveStateBudget, ActiveStateRuntime
from .context_pipeline import SparseContextPipeline
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .query import FeynMapQuery
from .snapshots import capture_repository_snapshot


BENCHMARK_SCHEMA = "feynmap.active_state_benchmark.v1"


def _context_budget(payload: Mapping[str, Any]) -> MinimalContextBudget:
    return MinimalContextBudget(
        max_tokens=int(payload.get("max_tokens", 3200)),
        max_nodes=int(payload.get("max_nodes", 24)),
        max_edges=int(payload.get("max_edges", 24)),
        initial_tokens=int(payload.get("initial_tokens", 900)),
        step_tokens=int(payload.get("step_tokens", 350)),
    )


def _active_budget(payload: Mapping[str, Any]) -> ActiveStateBudget:
    return ActiveStateBudget(
        max_nodes=int(payload.get("max_nodes", 32)),
        max_edges=int(payload.get("max_edges", 48)),
        max_regions=int(payload.get("max_regions", 8)),
        max_retrievals=int(payload.get("max_retrievals", 8)),
        max_open_questions=int(payload.get("max_open_questions", 8)),
        max_contradictions=int(payload.get("max_contradictions", 8)),
        max_concepts=int(payload.get("max_concepts", 32)),
    )


def _search_kwargs(step: Mapping[str, Any]) -> Dict[str, Any]:
    search = step.get("search") or {}
    if not isinstance(search, Mapping):
        search = {}
    return {
        "max_depth": int(search.get("max_depth", 4)),
        "beam_width": int(search.get("beam_width", 8)),
        "max_nodes": int(search.get("max_nodes", 64)),
        "direction": str(search.get("direction", "both")),
    }


def _essential_ids(
    query: FeynMapQuery,
    symbols: Sequence[str],
) -> Tuple[List[str], List[str]]:
    resolved: List[str] = []
    missing: List[str] = []
    for symbol in symbols:
        try:
            resolved.append(query.resolve(str(symbol)).id)
        except KeyError:
            missing.append(str(symbol))
    return resolved, missing


def _recall(selected: Sequence[str], essential: Sequence[str]) -> float:
    if not essential:
        return 1.0
    selected_set = set(selected)
    return float(sum(1 for item in essential if item in selected_set)) / float(len(essential))


def run_sequence(
    graph,
    snapshot_id: str,
    sequence: Mapping[str, Any],
    *,
    context_budget: Optional[MinimalContextBudget] = None,
    active_budget: Optional[ActiveStateBudget] = None,
) -> Dict[str, Any]:
    steps = sequence.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise ValueError("active-state sequence must include at least one step")

    context_budget = context_budget or MinimalContextBudget()
    active_budget = active_budget or ActiveStateBudget()
    baseline = SparseContextPipeline(graph)
    runtime = ActiveStateRuntime(
        graph,
        snapshot_id,
        budget=active_budget,
    )
    query = FeynMapQuery(graph)

    state = None
    cumulative_fresh_tokens = 0
    cumulative_active_turn_tokens = 0
    step_rows: List[Dict[str, Any]] = []

    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError("sequence step %d must be an object" % index)
        root = str(raw.get("root", ""))
        goal = str(raw.get("goal", raw.get("query", "")))
        if not root or not goal:
            raise ValueError("sequence step %d requires root and goal" % index)
        search_kwargs = _search_kwargs(raw)

        fresh = baseline.from_node(
            root,
            goal,
            context_budget=context_budget,
            **search_kwargs
        )
        cumulative_fresh_tokens += int(fresh.context.delivered_tokens)

        if state is None:
            transition = runtime.begin_from_node(
                root,
                goal,
                task=str(sequence.get("task", sequence.get("id", goal))),
                context_budget=context_budget,
                **search_kwargs
            )
        else:
            transition = runtime.continue_from_node(
                state,
                root,
                goal,
                context_budget=context_budget,
                **search_kwargs
            )
        state = transition.state
        cumulative_active_turn_tokens += int(transition.working_context_tokens)

        essential_symbols = [
            str(item)
            for item in raw.get("essential_symbols", []) or []
        ]
        essential_ids, missing_essential = _essential_ids(
            query,
            essential_symbols,
        )
        active_recall = _recall(state.active_node_ids, essential_ids)
        fresh_recall = _recall(
            fresh.context.selected_node_ids,
            essential_ids,
        )

        step_rows.append({
            "index": index,
            "id": str(raw.get("id", "step-%d" % index)),
            "root": root,
            "goal": goal,
            "fresh": {
                "stage": fresh.activation.stage,
                "effort": fresh.activation.effort,
                "delivered_tokens": int(fresh.context.delivered_tokens),
                "selected_nodes": len(fresh.context.selected_node_ids),
                "essential_recall": fresh_recall,
            },
            "active": {
                "stage": transition.retrieval.activation.stage,
                "effort": transition.retrieval.activation.effort,
                "working_context_tokens": int(transition.working_context_tokens),
                "compact_state_tokens": int(state.compact_tokens),
                "active_nodes": len(state.active_node_ids),
                "active_edges": len(state.active_edge_ids),
                "active_regions": len(state.active_region_ids),
                "reused_nodes": len(transition.reused_node_ids),
                "introduced_nodes": len(transition.introduced_node_ids),
                "dropped_nodes": len(transition.dropped_node_ids),
                "essential_recall": active_recall,
            },
            "essential_symbols": essential_symbols,
            "essential_ids": essential_ids,
            "missing_essential_symbols": missing_essential,
            "cumulative_fresh_context_tokens": cumulative_fresh_tokens,
            "retained_context_growth_avoided_tokens": max(
                0,
                cumulative_fresh_tokens - int(transition.working_context_tokens),
            ),
        })

    assert state is not None
    final_metrics = runtime.metrics(state)
    reuse_steps = sum(
        1 for row in step_rows
        if row["active"]["stage"] == "active_state"
    )
    reexpanded_steps = len(step_rows) - reuse_steps
    active_recalls = [row["active"]["essential_recall"] for row in step_rows]
    fresh_recalls = [row["fresh"]["essential_recall"] for row in step_rows]
    missing_symbols = [
        symbol
        for row in step_rows
        for symbol in row["missing_essential_symbols"]
    ]
    avoided = max(
        0,
        cumulative_fresh_tokens - int(final_metrics["working_context_tokens"]),
    )
    avoided_ratio = (
        float(avoided) / float(cumulative_fresh_tokens)
        if cumulative_fresh_tokens > 0
        else 0.0
    )

    return {
        "id": str(sequence.get("id", "sequence")),
        "task": str(sequence.get("task", sequence.get("id", "sequence"))),
        "step_count": len(step_rows),
        "steps": step_rows,
        "summary": {
            "reuse_steps": reuse_steps,
            "reexpanded_steps": reexpanded_steps,
            "reuse_ratio": float(reuse_steps) / float(len(step_rows)),
            "mean_fresh_essential_recall": (
                sum(fresh_recalls) / float(len(fresh_recalls))
                if fresh_recalls else 1.0
            ),
            "mean_active_essential_recall": (
                sum(active_recalls) / float(len(active_recalls))
                if active_recalls else 1.0
            ),
            "full_active_recall_steps": sum(
                1 for value in active_recalls if value >= 1.0
            ),
            "missing_essential_symbols": missing_symbols,
            "cumulative_fresh_context_tokens": cumulative_fresh_tokens,
            "final_active_working_context_tokens": int(
                final_metrics["working_context_tokens"]
            ),
            "final_compact_state_tokens": int(
                final_metrics["compact_state_tokens"]
            ),
            "retained_context_growth_avoided_tokens": avoided,
            "retained_context_growth_avoided_ratio": avoided_ratio,
            "cumulative_active_turn_context_tokens": cumulative_active_turn_tokens,
            "final_active_nodes": len(state.active_node_ids),
            "final_active_edges": len(state.active_edge_ids),
            "final_active_regions": len(state.active_region_ids),
        },
        "final_state": state.to_dict(),
    }


def run_benchmark(
    spec: Mapping[str, Any],
    project_path: Path,
) -> Dict[str, Any]:
    if spec.get("schema") not in (None, BENCHMARK_SCHEMA):
        raise ValueError("unsupported active-state benchmark schema: %s" % spec.get("schema"))

    analysis = spec.get("analysis") or {}
    if not isinstance(analysis, Mapping):
        analysis = {}
    graph = FeynMapEngine().analyze(
        str(project_path),
        language=str(analysis.get("language", "auto")),
        framework=str(analysis.get("framework", "auto")),
    )
    snapshot = capture_repository_snapshot(project_path, graph)

    context = spec.get("context") or {}
    active = spec.get("active_state") or {}
    if not isinstance(context, Mapping) or not isinstance(active, Mapping):
        raise ValueError("context and active_state benchmark settings must be objects")
    context_budget = _context_budget(context)
    active_budget = _active_budget(active)

    sequences = spec.get("sequences") or []
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("active-state benchmark requires sequences")

    results = [
        run_sequence(
            graph,
            snapshot.snapshot_id,
            sequence,
            context_budget=context_budget,
            active_budget=active_budget,
        )
        for sequence in sequences
        if isinstance(sequence, Mapping)
    ]
    summaries = [item["summary"] for item in results]
    total_steps = sum(item["step_count"] for item in results)
    total_reuse = sum(item["reuse_steps"] for item in summaries)
    total_fresh = sum(item["cumulative_fresh_context_tokens"] for item in summaries)
    total_final_active = sum(item["final_active_working_context_tokens"] for item in summaries)
    total_avoided = max(0, total_fresh - total_final_active)

    return {
        "schema": BENCHMARK_SCHEMA,
        "name": str(spec.get("name", "S4 active-state benchmark")),
        "snapshot_id": snapshot.snapshot_id,
        "analysis": {
            "graph_nodes": len(graph.nodes),
            "graph_edges": len(graph.edges),
            "language": str(analysis.get("language", "auto")),
            "framework": str(analysis.get("framework", "auto")),
        },
        "sequence_count": len(results),
        "step_count": total_steps,
        "sequences": results,
        "summary": {
            "reuse_steps": total_reuse,
            "reexpanded_steps": total_steps - total_reuse,
            "reuse_ratio": (
                float(total_reuse) / float(total_steps)
                if total_steps else 0.0
            ),
            "mean_active_essential_recall": (
                sum(item["mean_active_essential_recall"] for item in summaries)
                / float(len(summaries))
                if summaries else 1.0
            ),
            "full_active_recall_steps": sum(
                item["full_active_recall_steps"] for item in summaries
            ),
            "missing_essential_symbols": [
                symbol
                for item in summaries
                for symbol in item["missing_essential_symbols"]
            ],
            "cumulative_fresh_context_tokens": total_fresh,
            "final_active_working_context_tokens": total_final_active,
            "retained_context_growth_avoided_tokens": total_avoided,
            "retained_context_growth_avoided_ratio": (
                float(total_avoided) / float(total_fresh)
                if total_fresh else 0.0
            ),
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark S4 bounded active state over multi-step tasks.",
    )
    parser.add_argument("spec")
    parser.add_argument("project")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    project_path = Path(args.project).resolve()
    with spec_path.open("r", encoding="utf-8") as handle:
        spec = json.load(handle)

    result = run_benchmark(spec, project_path)
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
