"""Context Ranker v1E: transitive-necessity and adaptive semantic-frontier experiment.

v1B-v1D remain frozen. v1E attacks v1D's direct-neighbor completeness
assumption with independently specified transitive essentials. It compares:
1. direct outgoing behavioral context,
2. naive bounded behavioral expansion, and
3. task-conditioned adaptive semantic-frontier expansion.

Unlike the v1C compact state, v1E preserves the selected candidate-to-candidate
path spine so a judgment provider can see why a transitive candidate was added.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..context import StoredSnapshotContext, estimate_tokens
from ..core import EdgeKind, SemanticEdge, SemanticNode
from ..core.model import TIER_RANK
from ..engine import FeynMapEngine
from ..snapshots import capture_repository_snapshot
from .context_ranker_v1c import FROZEN_RELEVANCE_PROMPT, _compact_node
from .contracts import JudgmentProvider, JudgmentQuestion, JudgmentResult
from .jev import JevJudgmentProvider
from .ranking import RankedCandidate, baseline_rank
from .real_benchmark import _average, _rank_labels, _ranking_metrics

V1E_SCHEMA = "feynmap.context_ranker_v1e.v1"

NON_BEHAVIORAL_KINDS = {
    EdgeKind.CONTAINS,
    EdgeKind.OWNS,
    EdgeKind.IMPORTS,
    EdgeKind.RELATED_TO,
}

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "their", "this",
    "through", "to", "under", "uses", "using", "with", "within", "understand",
    "identify", "trace", "major", "core", "feyn", "map", "feynmap",
}


def _text_tokens(value: str) -> Set[str]:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    raw = re.findall(r"[A-Za-z0-9]+", text.lower())
    tokens: Set[str] = set()
    for token in raw:
        if len(token) <= 1 or token in _STOPWORDS:
            continue
        tokens.add(token)
        if token.endswith("ies") and len(token) > 4:
            tokens.add(token[:-3] + "y")
        elif token.endswith("es") and len(token) > 4:
            tokens.add(token[:-2])
        elif token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens


def _node_label(node: SemanticNode) -> str:
    return str(node.qualified_name or node.id or node.name)


def _candidate_payload(node: SemanticNode) -> Dict[str, Any]:
    return _compact_node(node.to_dict())


def _edge_payload(edge: SemanticEdge) -> Dict[str, Any]:
    return {
        "source": edge.source,
        "relationship": edge.kind.value,
        "target": edge.target,
        "confidence_tier": edge.confidence_tier.value,
    }


def _behavioral_edges(context: StoredSnapshotContext, node_id: str) -> List[SemanticEdge]:
    edges = [
        edge
        for edge in context.graph.outgoing(node_id)
        if edge.kind not in NON_BEHAVIORAL_KINDS and edge.target != node_id
    ]
    return sorted(
        edges,
        key=lambda edge: (
            -TIER_RANK[edge.confidence_tier],
            edge.kind.value,
            _node_label(context.graph.node(edge.target)) if context.graph.node(edge.target) else edge.target,
            edge.id,
        ),
    )


def _resolve_labels(context: StoredSnapshotContext, values: Sequence[str]) -> Tuple[Set[str], Dict[str, str]]:
    labels: Set[str] = set()
    ids: Dict[str, str] = {}
    for value in values:
        node = context.query.resolve(str(value))
        label = _node_label(node)
        labels.add(label)
        ids[label] = node.id
    return labels, ids


def _shortest_behavioral_depth(
    context: StoredSnapshotContext,
    root_id: str,
    target_id: str,
    *,
    max_depth: int,
) -> Optional[int]:
    if root_id == target_id:
        return 0
    queue = deque([(root_id, 0)])
    seen = {root_id}
    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in _behavioral_edges(context, node_id):
            if edge.target == target_id:
                return depth + 1
            if edge.target in seen:
                continue
            seen.add(edge.target)
            queue.append((edge.target, depth + 1))
    return None


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != V1E_SCHEMA:
        raise ValueError("unsupported Context Ranker v1E schema")
    retrieval = spec.get("retrieval") or {}
    if int(retrieval.get("max_depth", 0)) < 2:
        raise ValueError("v1E retrieval.max_depth must be at least 2")
    if int(retrieval.get("adaptive_max_candidates", 0)) <= 0:
        raise ValueError("v1E requires retrieval.adaptive_max_candidates")
    if int(retrieval.get("naive_max_candidates", 0)) <= 0:
        raise ValueError("v1E requires retrieval.naive_max_candidates")
    adaptive = spec.get("adaptive") or {}
    if int(adaptive.get("max_branch_expansions_per_depth", 0)) <= 0:
        raise ValueError("v1E requires adaptive.max_branch_expansions_per_depth")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1E requires tasks")
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("each v1E task must be an object")
        for key in ("id", "root", "description", "relevant", "essential"):
            if not task.get(key):
                raise ValueError("each v1E task requires %s" % key)
        if not set(task["essential"]).issubset(set(task["relevant"])):
            raise ValueError("v1E essential labels must be a subset of relevant labels")


def _task_labels(
    context: StoredSnapshotContext,
    task: Mapping[str, Any],
    *,
    max_depth: int,
) -> Tuple[Set[str], Set[str], Dict[str, int]]:
    root = context.query.resolve(str(task["root"]))
    relevant, _ = _resolve_labels(context, list(task["relevant"]))
    essential, essential_ids = _resolve_labels(context, list(task["essential"]))
    depths: Dict[str, int] = {}
    for label, node_id in essential_ids.items():
        depth = _shortest_behavioral_depth(context, root.id, node_id, max_depth=max_depth)
        if depth is None:
            raise ValueError(
                "v1E essential %r is not reachable from %r within behavioral depth %d"
                % (label, task["root"], max_depth)
            )
        if depth < 2:
            raise ValueError(
                "v1E essential %r is direct from %r; adversarial essentials must be transitive"
                % (label, task["root"])
            )
        depths[label] = depth
    return relevant, essential, depths


def _selection_bundle(
    context: StoredSnapshotContext,
    root: SemanticNode,
    candidate_ids: Sequence[str],
    edges: Sequence[SemanticEdge],
    provenance: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    candidates = [
        _candidate_payload(context.graph.node(node_id))
        for node_id in candidate_ids
        if context.graph.node(node_id) is not None
    ]
    relationships = [_edge_payload(edge) for edge in edges]
    bundle: Dict[str, Any] = {
        "root": _candidate_payload(root),
        "nodes": candidates,
        "relationships": relationships,
        "provenance": [
            dict(provenance[node_id])
            for node_id in candidate_ids
            if node_id in provenance
        ],
        "budget": {
            "included_nodes": 1 + len(candidates),
            "included_relationships": len(relationships),
            "truncated": False,
        },
    }
    bundle["budget"]["estimated_tokens"] = estimate_tokens(bundle)
    return bundle


def _direct_selection(
    context: StoredSnapshotContext,
    root: SemanticNode,
    *,
    max_candidates: int,
) -> Dict[str, Any]:
    edges = _behavioral_edges(context, root.id)
    direct_target_count = len({edge.target for edge in edges})
    candidate_ids: List[str] = []
    selected_edges: List[SemanticEdge] = []
    provenance: Dict[str, Dict[str, Any]] = {}
    seen: Set[str] = set()
    for edge in edges:
        if edge.target not in seen and len(candidate_ids) >= max_candidates:
            continue
        if edge.target not in seen:
            seen.add(edge.target)
            candidate_ids.append(edge.target)
            target = context.graph.node(edge.target)
            provenance[edge.target] = {
                "candidate": _node_label(target) if target else edge.target,
                "candidate_id": edge.target,
                "depth": 1,
                "introduced_by": _node_label(root),
                "relationship": edge.kind.value,
                "branch_anchor": _node_label(target) if target else edge.target,
                "anchor_overlap": 0,
            }
        if edge.target in seen:
            selected_edges.append(edge)
    covered = len(candidate_ids)
    return {
        "candidate_ids": candidate_ids,
        "edges": selected_edges,
        "provenance": provenance,
        "max_depth_reached": 1 if candidate_ids else 0,
        "expansion_count": 0,
        "direct_target_count": direct_target_count,
        "covered_direct_targets": covered,
        "declared_complete": covered >= direct_target_count,
        "stopped_reason": "direct outgoing behavioral targets covered",
    }


def _naive_selection(
    context: StoredSnapshotContext,
    root: SemanticNode,
    *,
    max_depth: int,
    max_candidates: int,
) -> Dict[str, Any]:
    candidate_ids: List[str] = []
    selected_edges: List[SemanticEdge] = []
    provenance: Dict[str, Dict[str, Any]] = {}
    seen = {root.id}
    frontier = [root.id]
    max_reached = 0
    expansion_count = 0
    saturated = False

    for depth in range(1, max_depth + 1):
        next_frontier: List[str] = []
        for source_id in frontier:
            outgoing = _behavioral_edges(context, source_id)
            if outgoing:
                expansion_count += 1
            for edge in outgoing:
                target_id = edge.target
                if target_id not in seen:
                    if len(candidate_ids) >= max_candidates:
                        saturated = True
                        continue
                    seen.add(target_id)
                    candidate_ids.append(target_id)
                    next_frontier.append(target_id)
                    target = context.graph.node(target_id)
                    source = context.graph.node(source_id)
                    anchor = (
                        provenance.get(source_id, {}).get("branch_anchor")
                        if source_id != root.id
                        else (_node_label(target) if target else target_id)
                    )
                    provenance[target_id] = {
                        "candidate": _node_label(target) if target else target_id,
                        "candidate_id": target_id,
                        "depth": depth,
                        "introduced_by": _node_label(source) if source else source_id,
                        "relationship": edge.kind.value,
                        "branch_anchor": anchor,
                        "anchor_overlap": 0,
                    }
                    max_reached = max(max_reached, depth)
                if target_id in seen and source_id in seen:
                    selected_edges.append(edge)
        frontier = next_frontier
        if not frontier or len(candidate_ids) >= max_candidates:
            break

    return {
        "candidate_ids": candidate_ids,
        "edges": selected_edges,
        "provenance": provenance,
        "max_depth_reached": max_reached,
        "expansion_count": expansion_count,
        "declared_complete": not saturated,
        "stopped_reason": "candidate ceiling" if saturated else "fixed behavioral depth exhausted",
    }


def _overlap(node: Optional[SemanticNode], task_tokens: Set[str]) -> int:
    if node is None:
        return 0
    return len(_text_tokens("%s %s %s" % (node.name, node.qualified_name or "", node.id)) & task_tokens)


def _branch_score(
    context: StoredSnapshotContext,
    node_id: str,
    task_tokens: Set[str],
    provenance: Mapping[str, Mapping[str, Any]],
) -> Tuple[float, int, int, int]:
    node = context.graph.node(node_id)
    outgoing = _behavioral_edges(context, node_id)
    node_overlap = _overlap(node, task_tokens)
    best_child_overlap = max(
        (_overlap(context.graph.node(edge.target), task_tokens) for edge in outgoing),
        default=0,
    )
    inherited = int(provenance.get(node_id, {}).get("anchor_overlap") or 0)
    score = (10.0 * node_overlap) + (8.0 * best_child_overlap) + (2.0 * inherited) + min(len(outgoing), 5) * 0.1
    return score, node_overlap, best_child_overlap, len(outgoing)


def _adaptive_selection(
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
        scored = []
        for node_id in frontier:
            score, node_overlap, child_overlap, fanout = _branch_score(
                context, node_id, task_tokens, provenance
            )
            if fanout <= 0:
                continue
            scored.append((score, node_overlap, child_overlap, fanout, node_id))
        scored.sort(key=lambda item: (-item[0], _node_label(context.graph.node(item[4])) if context.graph.node(item[4]) else item[4]))

        selected = [item for item in scored if item[1] > 0 or item[2] > 0 or int(provenance.get(item[4], {}).get("anchor_overlap") or 0) > 0]
        if not selected and fallback_branch_expansions > 0:
            selected = scored[:fallback_branch_expansions]
        selected = selected[:max_branch_expansions_per_depth]

        decisions.append(
            {
                "source_depth": depth,
                "frontier_size": len(frontier),
                "expand": [
                    {
                        "candidate": _node_label(context.graph.node(item[4])) if context.graph.node(item[4]) else item[4],
                        "score": round(item[0], 3),
                        "node_overlap": item[1],
                        "best_child_overlap": item[2],
                        "behavioral_fanout": item[3],
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
                        "branch_anchor": provenance.get(source_id, {}).get("branch_anchor")
                            or (_node_label(source) if source else source_id),
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
        "stopped_reason": "candidate ceiling" if saturated else "semantic frontier stabilized or depth exhausted",
        "task_tokens": sorted(task_tokens),
        "branch_decisions": decisions,
    }


def build_frontier_state(
    task: Mapping[str, Any],
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compact Jev state that preserves the transitive path spine."""
    root = bundle.get("root") or {}
    candidate_ids = {str(item.get("id") or "") for item in candidates}
    keep_ids = set(candidate_ids)
    root_id = str(root.get("id") or "") if isinstance(root, Mapping) else ""
    if root_id:
        keep_ids.add(root_id)
    relationships = []
    for edge in bundle.get("relationships") or []:
        if str(edge.get("source") or "") in keep_ids and str(edge.get("target") or "") in keep_ids:
            relationships.append(
                {
                    key: edge[key]
                    for key in ("source", "relationship", "target", "confidence_tier")
                    if key in edge
                }
            )
    return {
        "task": dict(task),
        "grounded_context": {
            "root": dict(root) if isinstance(root, Mapping) else root,
            "candidates": [dict(item) for item in candidates],
            "relationships": relationships,
            "path_provenance": list(bundle.get("provenance") or []),
            "selection_note": "Relationships include the compact root-to-candidate path spine, including candidate-to-candidate edges.",
        },
    }


def rerank_frontier(
    task: Mapping[str, Any],
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    provider: JudgmentProvider,
) -> Tuple[List[RankedCandidate], Optional[JudgmentResult], Dict[str, Any]]:
    baseline = baseline_rank(candidates)
    state = build_frontier_state(task, bundle, candidates)
    if not baseline:
        return [], None, state

    questions: Dict[str, JudgmentQuestion] = {}
    key_to_id: Dict[str, str] = {}
    for index, item in enumerate(baseline):
        key = "candidate_%d" % index
        key_to_id[key] = item.candidate_id
        questions[key] = JudgmentQuestion.noul(FROZEN_RELEVANCE_PROMPT % item.candidate_id)

    result = provider.evaluate(state, questions)
    probabilities: Dict[str, float] = {}
    for key, candidate_id in key_to_id.items():
        probability = float(result.answers[key].value)
        probabilities[candidate_id] = max(0.0, min(1.0, probability))

    ranked = [
        RankedCandidate(item.candidate, item.baseline_rank, probabilities[item.candidate_id])
        for item in baseline
    ]
    ranked.sort(
        key=lambda item: (
            -float(item.judgment_probability or 0.0),
            item.baseline_rank,
            item.candidate_id,
        )
    )
    return ranked, result, state


def _retrieval(candidates: Sequence[Mapping[str, Any]], relevant: Set[str], essential: Set[str]) -> Dict[str, Any]:
    labels = set(_rank_labels(baseline_rank(candidates)))
    return {
        "relevant_recall": len(labels & relevant) / len(relevant) if relevant else None,
        "essential_recall": len(labels & essential) / len(essential) if essential else None,
        "missing_relevant": sorted(relevant - labels),
        "missing_essential": sorted(essential - labels),
    }


def _row(
    context: StoredSnapshotContext,
    root: SemanticNode,
    selection: Mapping[str, Any],
    relevant: Set[str],
    essential: Set[str],
    description: str,
    *,
    ks: Sequence[int],
    provider=None,
) -> Dict[str, Any]:
    bundle = _selection_bundle(
        context,
        root,
        selection["candidate_ids"],
        selection["edges"],
        selection["provenance"],
    )
    candidates = list(bundle["nodes"])
    baseline = baseline_rank(candidates)
    retrieval = _retrieval(candidates, relevant, essential)
    row: Dict[str, Any] = {
        "candidate_count": len(candidates),
        "candidate_tokens": estimate_tokens(candidates),
        "compact_path_state_tokens": estimate_tokens(
            build_frontier_state({"description": description}, bundle, candidates)
        ),
        "max_depth_reached": selection.get("max_depth_reached"),
        "expansion_count": selection.get("expansion_count"),
        "declared_complete": bool(selection.get("declared_complete")),
        "stopped_reason": selection.get("stopped_reason"),
        "retrieval": retrieval,
        "baseline_order": _rank_labels(baseline),
        "baseline": _ranking_metrics(baseline, relevant, essential, ks),
        "provenance": list(bundle.get("provenance") or []),
    }
    for key in ("direct_target_count", "covered_direct_targets", "task_tokens", "branch_decisions"):
        if key in selection:
            row[key] = selection[key]

    if provider is not None and candidates:
        started = time.perf_counter()
        reranked, judgment, state = rerank_frontier(
            {"description": description},
            bundle,
            candidates,
            provider,
        )
        row["provider_elapsed_seconds"] = round(time.perf_counter() - started, 6)
        row["reranked_order"] = _rank_labels(reranked)
        row["reranked"] = _ranking_metrics(reranked, relevant, essential, ks)
        row["provider_state_tokens"] = estimate_tokens(state)
        if judgment is not None:
            row["usage"] = dict(judgment.usage)
            row["model"] = judgment.model
            row["request_id"] = judgment.request_id
    return row


def _recovery(direct_row: Mapping[str, Any], candidate_row: Mapping[str, Any], essential: Set[str]) -> Dict[str, Any]:
    direct_labels = set(direct_row.get("baseline_order") or [])
    candidate_labels = set(candidate_row.get("baseline_order") or [])
    recovered = (essential & candidate_labels) - (essential & direct_labels)
    added = max(0, int(candidate_row.get("candidate_count") or 0) - int(direct_row.get("candidate_count") or 0))
    return {
        "recovered_essential": sorted(recovered),
        "recovered_essential_count": len(recovered),
        "added_candidates": added,
        "marginal_recovery_efficiency": (len(recovered) / added) if added else None,
    }


def run_graph_experiment(
    context: StoredSnapshotContext,
    spec: Mapping[str, Any],
    provider=None,
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, Any]:
    _validate_spec(spec)
    retrieval_spec = spec.get("retrieval") or {}
    adaptive_spec = spec.get("adaptive") or {}
    max_depth = int(retrieval_spec.get("max_depth", 3))
    direct_max = int(retrieval_spec.get("direct_max_candidates", 30))
    adaptive_max = int(retrieval_spec.get("adaptive_max_candidates", 30))
    naive_max = int(retrieval_spec.get("naive_max_candidates", 80))
    per_depth = int(adaptive_spec.get("max_branch_expansions_per_depth", 2))
    fallback = int(adaptive_spec.get("fallback_branch_expansions", 1))

    task_rows: List[Dict[str, Any]] = []
    for task in spec["tasks"]:
        root = context.query.resolve(str(task["root"]))
        relevant, essential, essential_depths = _task_labels(
            context, task, max_depth=max_depth
        )

        direct_selection = _direct_selection(context, root, max_candidates=direct_max)
        naive_selection = _naive_selection(
            context, root, max_depth=max_depth, max_candidates=naive_max
        )
        adaptive_selection = _adaptive_selection(
            context,
            root,
            str(task["description"]),
            max_depth=max_depth,
            max_candidates=adaptive_max,
            max_branch_expansions_per_depth=per_depth,
            fallback_branch_expansions=fallback,
        )

        direct_row = _row(
            context, root, direct_selection, relevant, essential,
            str(task["description"]), ks=ks,
        )
        naive_row = _row(
            context, root, naive_selection, relevant, essential,
            str(task["description"]), ks=ks,
        )
        adaptive_row = _row(
            context, root, adaptive_selection, relevant, essential,
            str(task["description"]), ks=ks, provider=provider,
        )

        direct_recall = direct_row["retrieval"]["essential_recall"]
        direct_row["false_complete"] = bool(
            direct_row["declared_complete"]
            and direct_recall is not None
            and float(direct_recall) < 1.0
        )

        task_rows.append(
            {
                "id": task["id"],
                "root": task["root"],
                "description": task["description"],
                "golden_relevant": sorted(relevant),
                "golden_essential": sorted(essential),
                "essential_shortest_depth": essential_depths,
                "direct": direct_row,
                "naive": naive_row,
                "adaptive": adaptive_row,
                "adaptive_recovery": _recovery(direct_row, adaptive_row, essential),
                "naive_recovery": _recovery(direct_row, naive_row, essential),
            }
        )

    def summary_for(key: str) -> Dict[str, Any]:
        rows = [task[key] for task in task_rows]
        relevant_values = [
            row["retrieval"]["relevant_recall"]
            for row in rows
            if row["retrieval"]["relevant_recall"] is not None
        ]
        essential_values = [
            row["retrieval"]["essential_recall"]
            for row in rows
            if row["retrieval"]["essential_recall"] is not None
        ]
        payload: Dict[str, Any] = {
            "mean_candidate_count": sum(row["candidate_count"] for row in rows) / len(rows),
            "mean_compact_path_state_tokens": sum(row["compact_path_state_tokens"] for row in rows) / len(rows),
            "mean_relevant_recall": sum(relevant_values) / len(relevant_values) if relevant_values else None,
            "mean_essential_recall": sum(essential_values) / len(essential_values) if essential_values else None,
            "mean_max_depth_reached": sum(float(row["max_depth_reached"] or 0) for row in rows) / len(rows),
            "mean_expansion_count": sum(float(row["expansion_count"] or 0) for row in rows) / len(rows),
            "baseline": _average([row["baseline"] for row in rows]),
        }
        reranked = [row["reranked"] for row in rows if "reranked" in row]
        if reranked:
            payload["reranked"] = _average(reranked)
            usage = {"input_tokens": 0, "output_tokens": 0}
            elapsed = 0.0
            for row in rows:
                elapsed += float(row.get("provider_elapsed_seconds") or 0.0)
                for token_key in usage:
                    value = (row.get("usage") or {}).get(token_key)
                    if isinstance(value, (int, float)):
                        usage[token_key] += value
            payload["usage"] = usage
            payload["provider_elapsed_seconds"] = round(elapsed, 6)
        return payload

    false_complete_count = sum(1 for task in task_rows if task["direct"]["false_complete"])
    adaptive_recovered = sum(task["adaptive_recovery"]["recovered_essential_count"] for task in task_rows)
    adaptive_added = sum(task["adaptive_recovery"]["added_candidates"] for task in task_rows)
    naive_recovered = sum(task["naive_recovery"]["recovered_essential_count"] for task in task_rows)
    naive_added = sum(task["naive_recovery"]["added_candidates"] for task in task_rows)

    result: Dict[str, Any] = {
        "schema": V1E_SCHEMA,
        "name": spec.get("name"),
        "snapshot_id": context.snapshot.snapshot_id,
        "repository_key": context.snapshot.repository_key,
        "task_count": len(task_rows),
        "direct_summary": summary_for("direct"),
        "naive_summary": summary_for("naive"),
        "adaptive_summary": summary_for("adaptive"),
        "false_completeness": {
            "count": false_complete_count,
            "rate": false_complete_count / len(task_rows) if task_rows else None,
        },
        "recovery_efficiency": {
            "adaptive": (adaptive_recovered / adaptive_added) if adaptive_added else None,
            "naive": (naive_recovered / naive_added) if naive_added else None,
            "adaptive_recovered_essential": adaptive_recovered,
            "adaptive_added_candidates": adaptive_added,
            "naive_recovered_essential": naive_recovered,
            "naive_added_candidates": naive_added,
        },
        "tasks": task_rows,
    }
    return result


def run_repository_experiment(
    project_path: str,
    spec: Mapping[str, Any],
    provider=None,
) -> Dict[str, Any]:
    root = Path(project_path).resolve()
    graph = FeynMapEngine().analyze(str(root))
    snapshot = capture_repository_snapshot(root, graph)
    return run_graph_experiment(StoredSnapshotContext(snapshot, graph), spec, provider)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Context Ranker v1E transitive-necessity experiment"
    )
    parser.add_argument("project", help="Repository path to analyze")
    parser.add_argument("--spec", default="experiments/context_ranker_v1e.json")
    parser.add_argument(
        "--jev",
        action="store_true",
        help="Rerank only the adaptive semantic-frontier candidates with Jev",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    provider = JevJudgmentProvider() if args.jev else None
    result = run_repository_experiment(args.project, spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
