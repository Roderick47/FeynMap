"""Context Ranker v1H: diversified adaptive frontier.

v1H keeps the v1F historical task set and Jev prompt frozen. It changes only
adaptive branch selection: one expansion slot is reserved for a structurally
plausible zero-lexical-overlap branch whenever the per-depth budget allows it.
This prevents keyword-rich branches from completely suppressing cross-runtime
or otherwise indirect structural bridges.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..context import StoredSnapshotContext
from ..core import SemanticNode
from .context_ranker_v1e import (
    _behavioral_edges,
    _branch_score,
    _direct_selection,
    _node_label,
    _overlap,
    _text_tokens,
)
from .context_ranker_v1f import run_historical_experiment
from .jev import JevJudgmentProvider

V1H_SCHEMA = "feynmap.context_ranker_v1h.v1"


def _has_semantic_signal(
    item: Tuple[float, int, int, int, str],
    provenance: Mapping[str, Mapping[str, Any]],
) -> bool:
    return bool(
        item[1] > 0
        or item[2] > 0
        or int(provenance.get(item[4], {}).get("anchor_overlap") or 0) > 0
    )


def adaptive_selection_v1h(
    context: StoredSnapshotContext,
    root: SemanticNode,
    description: str,
    *,
    max_depth: int,
    max_candidates: int,
    max_branch_expansions_per_depth: int,
    fallback_branch_expansions: int,
) -> Dict[str, Any]:
    direct = _direct_selection(context, root, max_candidates=max_candidates)
    candidate_ids = list(direct["candidate_ids"])
    selected_edges = list(direct["edges"])
    provenance: Dict[str, Dict[str, Any]] = {
        key: dict(value) for key, value in direct["provenance"].items()
    }
    seen = {root.id} | set(candidate_ids)
    task_tokens = _text_tokens(description)

    for node_id in candidate_ids:
        node = context.graph.node(node_id)
        provenance[node_id]["anchor_overlap"] = _overlap(node, task_tokens)

    frontier = list(candidate_ids)
    expansion_count = 0
    max_reached = 1 if candidate_ids else 0
    decisions: List[Dict[str, Any]] = []
    saturated = len(candidate_ids) >= max_candidates

    for depth in range(1, max_depth):
        if not frontier or saturated:
            break

        scored: List[Tuple[float, int, int, int, str]] = []
        for node_id in frontier:
            score, node_overlap, child_overlap, fanout = _branch_score(
                context, node_id, task_tokens, provenance
            )
            if fanout <= 0:
                continue
            scored.append((score, node_overlap, child_overlap, fanout, node_id))
        scored.sort(
            key=lambda item: (
                -item[0],
                _node_label(context.graph.node(item[4]))
                if context.graph.node(item[4])
                else item[4],
            )
        )

        semantic = [item for item in scored if _has_semantic_signal(item, provenance)]
        exploratory = [item for item in scored if not _has_semantic_signal(item, provenance)]
        limit = max(1, int(max_branch_expansions_per_depth))

        # Preserve at least one semantic slot when semantic evidence exists.
        reserve = min(
            max(0, int(fallback_branch_expansions)),
            max(0, limit - 1),
        )
        selected_with_mode: List[Tuple[Tuple[float, int, int, int, str], str]] = []

        if semantic:
            semantic_slots = max(1, limit - reserve)
            for item in semantic[:semantic_slots]:
                selected_with_mode.append((item, "semantic"))
            if exploratory and len(selected_with_mode) < limit:
                for item in exploratory[: min(reserve or 1, limit - len(selected_with_mode))]:
                    selected_with_mode.append((item, "exploration"))
            if len(selected_with_mode) < limit:
                already = {item[0][4] for item in selected_with_mode}
                for item in semantic:
                    if item[4] in already:
                        continue
                    selected_with_mode.append((item, "semantic"))
                    if len(selected_with_mode) >= limit:
                        break
        elif fallback_branch_expansions > 0:
            for item in scored[: min(limit, int(fallback_branch_expansions))]:
                selected_with_mode.append((item, "fallback"))

        selected = [item for item, _ in selected_with_mode]
        mode_by_id = {item[4]: mode for item, mode in selected_with_mode}

        decisions.append(
            {
                "source_depth": depth,
                "frontier_size": len(frontier),
                "expand": [
                    {
                        "candidate": (
                            _node_label(context.graph.node(item[4]))
                            if context.graph.node(item[4])
                            else item[4]
                        ),
                        "score": round(item[0], 3),
                        "node_overlap": item[1],
                        "best_child_overlap": item[2],
                        "behavioral_fanout": item[3],
                        "selection_mode": mode_by_id[item[4]],
                    }
                    for item in selected
                ],
            }
        )
        if not selected:
            break

        next_frontier: List[str] = []
        for _, node_overlap, child_overlap, _, source_id in selected:
            expansion_count += 1
            source = context.graph.node(source_id)
            inherited = max(
                int(provenance.get(source_id, {}).get("anchor_overlap") or 0),
                node_overlap,
                child_overlap,
            )
            for edge in _behavioral_edges(context, source_id):
                target_id = edge.target
                if target_id not in seen:
                    if len(candidate_ids) >= max_candidates:
                        saturated = True
                        break
                    seen.add(target_id)
                    candidate_ids.append(target_id)
                    next_frontier.append(target_id)
                    target = context.graph.node(target_id)
                    provenance[target_id] = {
                        "candidate": _node_label(target) if target else target_id,
                        "candidate_id": target_id,
                        "depth": depth + 1,
                        "introduced_by": _node_label(source) if source else source_id,
                        "relationship": edge.kind.value,
                        "branch_anchor": (
                            provenance.get(source_id, {}).get("branch_anchor")
                            or (_node_label(source) if source else source_id)
                        ),
                        "anchor_overlap": inherited,
                    }
                    max_reached = max(max_reached, depth + 1)
                if target_id in seen:
                    selected_edges.append(edge)
            if saturated:
                break
        frontier = next_frontier

    return {
        "candidate_ids": candidate_ids,
        "edges": selected_edges,
        "provenance": provenance,
        "max_depth_reached": max_reached,
        "expansion_count": expansion_count,
        "declared_complete": not saturated,
        "stopped_reason": (
            "candidate ceiling"
            if saturated
            else "diversified semantic frontier stabilized or depth exhausted"
        ),
        "task_tokens": sorted(task_tokens),
        "branch_decisions": decisions,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Context Ranker v1H diversified frontier on frozen v1F tasks"
    )
    parser.add_argument("repository", help="Local Git checkout of the external repository")
    parser.add_argument("--spec", default="experiments/context_ranker_v1f.json")
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    if args.task:
        selected = set(args.task)
        spec = dict(spec)
        spec["tasks"] = [task for task in spec["tasks"] if task.get("id") in selected]
        missing = selected - {str(task.get("id")) for task in spec["tasks"]}
        if missing:
            raise ValueError("unknown v1H task ids: %s" % ", ".join(sorted(missing)))

    provider = JevJudgmentProvider() if args.jev else None
    result = run_historical_experiment(
        args.repository,
        spec,
        provider,
        adaptive_selector=adaptive_selection_v1h,
    )
    result["schema"] = V1H_SCHEMA
    result["name"] = "Context Ranker v1H - diversified adaptive frontier on frozen Wikonomi V2 tasks"
    result["frontier_policy"] = {
        "base": "v1E adaptive semantic frontier",
        "change": "reserve a branch-expansion slot for zero-overlap structural exploration when possible",
        "gold_labels_used_for_selection": False,
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
