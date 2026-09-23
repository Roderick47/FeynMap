"""Context Ranker v1I: semantic + structural bridge frontier.

v1I keeps the frozen v1F historical tasks and Jev prompt. It replaces v1H's
"zero-overlap exploration" slot with a canonical structural-bridge slot scored
only from graph facts: relationship kind, repository-local continuation,
cross-language transition, and downstream boundary richness.

No gold labels participate in selection.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..context import StoredSnapshotContext
from ..core import EdgeKind, SemanticNode
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

V1I_SCHEMA = "feynmap.context_ranker_v1i.v1"

# Canonical relationship weights only. These encode how strongly a relation
# tends to cross an architectural/composition boundary, independent of language
# or framework names.
_RELATION_WEIGHT = {
    EdgeKind.RENDERS.value: 3.0,
    EdgeKind.LOADS.value: 3.0,
    EdgeKind.REQUESTS.value: 3.0,
    EdgeKind.ROUTES_TO.value: 3.0,
    EdgeKind.CONNECTS_TO.value: 3.0,
    EdgeKind.SPAWNS.value: 3.0,
    EdgeKind.EMITS.value: 2.5,
    EdgeKind.SUBSCRIBES.value: 2.5,
    EdgeKind.FLOWS_TO.value: 2.5,
    EdgeKind.EXTENDS.value: 2.5,
    EdgeKind.DEPENDS_ON.value: 1.5,
    EdgeKind.INVOKES.value: 1.5,
    EdgeKind.AWAITS.value: 1.0,
    EdgeKind.IMPLEMENTS.value: 1.0,
    EdgeKind.PERSISTS.value: 1.0,
    EdgeKind.SERIALIZES.value: 1.0,
    EdgeKind.VALIDATES.value: 1.0,
    EdgeKind.READS.value: 0.75,
    EdgeKind.WRITES.value: 0.75,
    EdgeKind.MUTATES.value: 0.75,
    EdgeKind.CREATES.value: 0.75,
    EdgeKind.DELETES.value: 0.75,
    EdgeKind.USES_DATA.value: 0.75,
    EdgeKind.CALLS.value: 0.25,
}


def _local(node: Optional[SemanticNode]) -> bool:
    return bool(node is not None and node.location is not None)


def _parent_for(
    context: StoredSnapshotContext,
    root: SemanticNode,
    node_id: str,
    provenance: Mapping[str, Mapping[str, Any]],
) -> Optional[SemanticNode]:
    parent_id = provenance.get(node_id, {}).get("introduced_by_id")
    if parent_id:
        return context.graph.node(str(parent_id))
    if int(provenance.get(node_id, {}).get("depth") or 0) == 1:
        return root
    return None


def _structural_bridge_score(
    context: StoredSnapshotContext,
    root: SemanticNode,
    node_id: str,
    provenance: Mapping[str, Mapping[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    node = context.graph.node(node_id)
    if node is None:
        return 0.0, {}

    parent = _parent_for(context, root, node_id, provenance)
    relationship = str(provenance.get(node_id, {}).get("relationship") or "")
    outgoing = _behavioral_edges(context, node_id)

    local_edges = [
        edge for edge in outgoing if _local(context.graph.node(edge.target))
    ]
    local_children = len({edge.target for edge in local_edges})
    local_kinds = {edge.kind.value for edge in local_edges}
    local_boundary_weight = sum(
        _RELATION_WEIGHT.get(edge.kind.value, 0.5) for edge in local_edges
    )
    cross_language_children = 0
    for edge in local_edges:
        child = context.graph.node(edge.target)
        if (
            node.language
            and child is not None
            and child.language
            and child.language != node.language
        ):
            cross_language_children += 1

    cross_language_from_parent = bool(
        parent is not None
        and parent.language
        and node.language
        and parent.language != node.language
    )

    relation_weight = _RELATION_WEIGHT.get(relationship, 0.5)
    score = (
        2.0 * relation_weight
        + (4.0 if cross_language_from_parent else 0.0)
        + 1.5 * local_boundary_weight
        + 0.5 * local_children
        + 0.75 * cross_language_children
        + 0.25 * len(local_kinds)
    )

    # Avoid spending the bridge slot on a repository dead-end such as a local
    # wrapper whose only continuation is an external framework type.
    if outgoing and not local_edges:
        score -= 2.0

    details = {
        "relationship": relationship,
        "cross_language_from_parent": cross_language_from_parent,
        "local_children": local_children,
        "cross_language_children": cross_language_children,
        "local_edge_kinds": sorted(local_kinds),
        "structural_score": round(score, 3),
    }
    return score, details


def adaptive_selection_v1i(
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
    for node_id in candidate_ids:
        provenance[node_id]["introduced_by_id"] = root.id

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
        structural: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        for node_id in frontier:
            score, node_overlap, child_overlap, fanout = _branch_score(
                context, node_id, task_tokens, provenance
            )
            if fanout <= 0:
                continue
            item = (score, node_overlap, child_overlap, fanout, node_id)
            scored.append(item)
            structural[node_id] = _structural_bridge_score(
                context, root, node_id, provenance
            )

        scored.sort(
            key=lambda item: (
                -item[0],
                _node_label(context.graph.node(item[4]))
                if context.graph.node(item[4])
                else item[4],
            )
        )
        limit = max(1, int(max_branch_expansions_per_depth))
        selected_with_mode: List[Tuple[Tuple[float, int, int, int, str], str]] = []

        # Slot 1: strongest task-semantic branch, using the frozen v1E score.
        semantic = [
            item
            for item in scored
            if (
                item[1] > 0
                or item[2] > 0
                or int(provenance.get(item[4], {}).get("anchor_overlap") or 0) > 0
            )
        ]
        if semantic:
            selected_with_mode.append((semantic[0], "semantic"))
        elif scored and fallback_branch_expansions > 0:
            selected_with_mode.append((scored[0], "fallback"))

        # Slot 2+: strongest repository-local architectural bridge(s), regardless
        # of lexical overlap. Do not repeat the semantic candidate.
        selected_ids = {item[0][4] for item in selected_with_mode}
        bridge_candidates = [item for item in scored if item[4] not in selected_ids]
        bridge_candidates.sort(
            key=lambda item: (
                -structural[item[4]][0],
                -item[0],
                _node_label(context.graph.node(item[4]))
                if context.graph.node(item[4])
                else item[4],
            )
        )
        for item in bridge_candidates:
            if len(selected_with_mode) >= limit:
                break
            selected_with_mode.append((item, "structural_bridge"))

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
                        **structural[item[4]][1],
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
                        "introduced_by_id": source_id,
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
            else "semantic + structural bridge frontier stabilized or depth exhausted"
        ),
        "task_tokens": sorted(task_tokens),
        "branch_decisions": decisions,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Context Ranker v1I structural-bridge frontier on frozen v1F tasks"
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
        spec["tasks"] = [
            task for task in spec["tasks"] if task.get("id") in selected
        ]
        missing = selected - {str(task.get("id")) for task in spec["tasks"]}
        if missing:
            raise ValueError(
                "unknown v1I task ids: %s" % ", ".join(sorted(missing))
            )

    provider = JevJudgmentProvider() if args.jev else None
    result = run_historical_experiment(
        args.repository,
        spec,
        provider,
        adaptive_selector=adaptive_selection_v1i,
    )
    result["schema"] = V1I_SCHEMA
    result["name"] = (
        "Context Ranker v1I - semantic + structural bridge frontier "
        "on frozen Wikonomi V2 tasks"
    )
    result["frontier_policy"] = {
        "base": "v1E semantic scoring with v1H diversity lesson",
        "change": (
            "one task-semantic slot plus canonical structural-bridge slots "
            "scored from repository-local continuation and boundary topology"
        ),
        "gold_labels_used_for_selection": False,
        "language_specific_rules": False,
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
