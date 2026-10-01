"""P2.4 behavior-aware delivery over an already activated sparse search.

P2.3a deliberately remains a symbol-selection checkpoint.  This module is a
P2.4-only bridge between S3 symbol delivery and source-body extraction: it may
retain a very small continuation of *already activated*, source-backed behavior
when the selected task anchor reaches a dependency that S3 omitted.

It never activates a new node, never invents an edge, and never upgrades source
evidence.  Unknown remains unknown when the bounded continuation cannot fit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .behavior import BehaviorKind, BehaviorObservation
from .behavioral_context import BehavioralContextBuilder
from .context import estimate_tokens
from .core import EdgeKind, EvidenceKind, SemanticEdge, SemanticGraph
from .delivery_channels import DeliveryChannelPolicy, file_channel, task_channel
from .judgment.search import GuidedSearchResult
from .minimal_context import MinimalContextBudget, MinimalContextPacker, MinimalContextResult
from .relevance import RelevanceDecision, TaskEvidenceProfile


_CONTINUATION_EDGE_KINDS = {
    EdgeKind.CALLS,
    EdgeKind.INVOKES,
    EdgeKind.VALIDATES,
    EdgeKind.USES_DATA,
}


def _tokens(value: str) -> Set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    spaced = re.sub(r"[_./:\-]+", " ", spaced)
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9$]+", spaced)
        if len(token) >= 2
    }


def _source_backed(edge: SemanticEdge) -> bool:
    return bool(
        edge.kind in _CONTINUATION_EDGE_KINDS
        and any(
            evidence.location is not None
            and evidence.kind in {
                EvidenceKind.STATIC,
                EvidenceKind.TEST,
                EvidenceKind.RUNTIME,
            }
            for evidence in edge.evidence
        )
    )


@dataclass(frozen=True)
class BehavioralContinuationResult:
    context: MinimalContextResult
    added_node_ids: Sequence[str]
    added_edge_ids: Sequence[str]
    considered_paths: int
    omitted_due_budget: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added_node_ids": list(self.added_node_ids),
            "added_edge_ids": list(self.added_edge_ids),
            "considered_paths": int(self.considered_paths),
            "omitted_due_budget": int(self.omitted_due_budget),
            "context_sufficient": bool(self.context.sufficient),
        }


class BehavioralSymbolContinuation:
    """Retain a bounded source-backed dependency chain from task anchors.

    The continuation is intentionally narrow:
    - outgoing behavioral edges only;
    - targets must already exist in the S2 activation result;
    - source-backed STATIC/TEST/RUNTIME evidence is mandatory;
    - at most ``max_hops`` and ``max_added_nodes``;
    - the original S3 token/node/edge budget remains authoritative.
    """

    def __init__(
        self,
        graph: SemanticGraph,
        *,
        max_hops: int = 2,
        max_added_nodes: int = 3,
        max_seed_anchors: int = 2,
    ) -> None:
        self.graph = graph
        self.packer = MinimalContextPacker(graph)
        self.max_hops = max(1, int(max_hops))
        self.max_added_nodes = max(1, int(max_added_nodes))
        self.max_seed_anchors = max(1, int(max_seed_anchors))

    def extend(
        self,
        task: str,
        search: GuidedSearchResult,
        context: MinimalContextResult,
        *,
        budget: Optional[MinimalContextBudget] = None,
        delivery_policy: Optional[DeliveryChannelPolicy] = None,
    ) -> BehavioralContinuationResult:
        requested = (budget or MinimalContextBudget()).normalized()
        if not search.hits or not context.selected_node_ids:
            return BehavioralContinuationResult(context, (), (), 0, 0)

        hit_by_id = {hit.node.id: hit for hit in search.hits}
        active_ids = set(hit_by_id)
        edge_by_id = {edge.id: edge for edge in search.edges}
        outgoing: Dict[str, List[SemanticEdge]] = {}
        for edge in search.edges:
            if (
                edge.source in active_ids
                and edge.target in active_ids
                and _source_backed(edge)
            ):
                outgoing.setdefault(edge.source, []).append(edge)
        if not outgoing:
            return BehavioralContinuationResult(context, (), (), 0, 0)

        selected_nodes = set(context.selected_node_ids)
        selected_edges = set(context.selected_edge_ids)
        anchors = list(context.payload.get("anchors", ()))
        node_scores = self.packer._node_scores(
            search,
            hit_by_id,
            [edge for edge in search.edges if edge.source in active_ids and edge.target in active_ids],
        )
        query_terms = _tokens(task)
        desired_channel = task_channel(task)

        seed_candidates = []
        root_ids = {node.id for node in search.roots}
        for node_id in selected_nodes:
            hit = hit_by_id.get(node_id)
            node = self.graph.node(node_id)
            if hit is None or node is None or node.location is None:
                continue
            terms = _tokens("%s %s %s" % (
                node.name,
                node.qualified_name or "",
                node.location.path,
            ))
            overlap = len(query_terms & terms) / float(max(1, len(query_terms)))
            channel_bonus = 0.45 if file_channel(node.location.path) == desired_channel else 0.0
            root_bonus = 0.75 if node_id in root_ids else 0.0
            seed_candidates.append((
                node_scores.get(node_id, 0.0) + 2.2 * overlap + channel_bonus + root_bonus,
                node_id,
            ))
        seed_candidates.sort(key=lambda item: (-item[0], item[1]))
        seeds = [node_id for _, node_id in seed_candidates[: self.max_seed_anchors]]
        if not seeds:
            return BehavioralContinuationResult(context, (), (), 0, 0)

        # Candidate path tuples are (score, target_id, edge_ids, node_ids).
        # Selected intermediate nodes are traversable without being re-added;
        # this is what lets a test -> selected wrapper -> omitted policy chain
        # survive without broadening activation.
        candidates: List[Tuple[float, str, Tuple[str, ...], Tuple[str, ...]]] = []
        considered = 0
        seen_states: Set[Tuple[str, int]] = set()
        queue: List[Tuple[str, int, Tuple[str, ...], Tuple[str, ...], str]] = [
            (seed, 0, (), (), seed) for seed in seeds
        ]
        while queue:
            current, depth, path_edges, path_nodes, seed = queue.pop(0)
            state = (current, depth)
            if state in seen_states:
                continue
            seen_states.add(state)
            if depth >= self.max_hops:
                continue
            for edge in sorted(outgoing.get(current, ()), key=lambda item: item.id):
                target = edge.target
                if target == seed or target in path_nodes:
                    continue
                considered += 1
                next_edges = path_edges + (edge.id,)
                next_nodes = path_nodes + (target,)
                target_node = self.graph.node(target)
                if target_node is None or target_node.location is None:
                    continue
                target_terms = _tokens("%s %s %s" % (
                    target_node.name,
                    target_node.qualified_name or "",
                    target_node.location.path,
                ))
                overlap = len(query_terms & target_terms) / float(max(1, len(query_terms)))
                edge_bonus = {
                    EdgeKind.CALLS: 1.00,
                    EdgeKind.INVOKES: 1.00,
                    EdgeKind.VALIDATES: 0.95,
                    EdgeKind.USES_DATA: 0.70,
                }.get(edge.kind, 0.5)
                score = (
                    node_scores.get(target, 0.0)
                    + 1.4 * edge_bonus
                    + 2.0 * overlap
                    + (0.30 if target_node.location.path != self.graph.node(current).location.path else 0.0)
                    - 0.15 * depth
                )
                if target not in selected_nodes:
                    candidates.append((score, target, next_edges, next_nodes))
                # Continue through both selected and not-yet-selected activated
                # symbols; admission remains atomic and budget checked later.
                queue.append((target, depth + 1, next_edges, next_nodes, seed))

        candidates.sort(key=lambda row: (-row[0], len(row[2]), row[1], row[2]))
        added_nodes: List[str] = []
        added_edges: List[str] = []
        omitted_budget = 0
        current_nodes = set(selected_nodes)
        current_edges = set(selected_edges)

        for _, target, path_edges, path_nodes in candidates:
            if target in current_nodes:
                continue
            missing_nodes = [node_id for node_id in path_nodes if node_id not in current_nodes]
            if len(set(added_nodes) | set(missing_nodes)) > self.max_added_nodes:
                continue
            # Keep only real activated source-backed edges whose endpoints will
            # be present after this admission.  A path can traverse an already
            # selected node without fabricating its relation.
            candidate_nodes = current_nodes | set(missing_nodes)
            missing_edges = []
            for edge_id in path_edges:
                edge = edge_by_id.get(edge_id)
                if (
                    edge is not None
                    and _source_backed(edge)
                    and edge.source in candidate_nodes
                    and edge.target in candidate_nodes
                    and edge_id not in current_edges
                ):
                    missing_edges.append(edge_id)
            candidate_edges = current_edges | set(missing_edges)
            candidate_anchors = list(anchors)
            if not candidate_nodes.intersection(selected_nodes):
                candidate_anchors.append(target)
            if self.packer._fits(
                search,
                requested,
                candidate_nodes,
                candidate_edges,
                candidate_anchors,
                delivery_policy=delivery_policy,
            ):
                current_nodes = candidate_nodes
                current_edges = candidate_edges
                for node_id in missing_nodes:
                    if node_id not in added_nodes:
                        added_nodes.append(node_id)
                for edge_id in missing_edges:
                    if edge_id not in added_edges:
                        added_edges.append(edge_id)
                if len(added_nodes) >= self.max_added_nodes:
                    break
            else:
                omitted_budget += 1

        if not added_nodes and not added_edges:
            return BehavioralContinuationResult(context, (), (), considered, omitted_budget)

        payload = self.packer._payload(
            search,
            sorted(current_nodes, key=lambda item: (-node_scores.get(item, 0.0), item)),
            sorted(current_edges),
            anchors,
        )
        delivered_tokens = estimate_tokens(payload)
        if delivered_tokens > requested.max_tokens:
            raise ValueError("behavioral symbol continuation exceeded S3 token budget")

        critical = list(context.critical_node_ids)
        for node_id in added_nodes:
            if node_id not in critical:
                critical.append(node_id)
        extended = MinimalContextResult(
            payload=payload,
            selected_node_ids=tuple(sorted(current_nodes, key=lambda item: (-node_scores.get(item, 0.0), item))),
            selected_edge_ids=tuple(sorted(current_edges)),
            activated_tokens=context.activated_tokens,
            delivered_tokens=delivered_tokens,
            activated_nodes=context.activated_nodes,
            delivered_nodes=len(current_nodes),
            critical_node_ids=tuple(critical),
            sufficient=bool(context.sufficient and omitted_budget == 0),
            selected_budget_tokens=context.selected_budget_tokens,
            packing_iterations=context.packing_iterations,
            unresolved_query_identifiers=tuple(context.unresolved_query_identifiers),
        )
        return BehavioralContinuationResult(
            extended,
            tuple(added_nodes),
            tuple(added_edges),
            considered,
            omitted_budget,
        )


class TaskConditionedBehavioralContextBuilder(BehavioralContextBuilder):
    """P2.4 builder that keeps named wrapper returns in test-oriented tasks."""

    def _reserve_task_dimensions(
        self,
        useful: Sequence[Tuple[BehaviorObservation, RelevanceDecision]],
        profile: TaskEvidenceProfile,
    ) -> Tuple[List[Tuple[BehaviorObservation, RelevanceDecision]], set]:
        ordered, reserved = super()._reserve_task_dimensions(useful, profile)
        reserved = set(reserved)
        if profile.task_type != "test_behavior" or not profile.identifiers:
            return ordered, reserved

        additions: List[Tuple[BehaviorObservation, RelevanceDecision]] = []
        for identifier in profile.identifiers:
            candidates = []
            for item in useful:
                observation = item[0]
                if observation.kind != BehaviorKind.RETURN:
                    continue
                node = self.graph.node(observation.symbol_id)
                if node is None or node.name != identifier:
                    continue
                candidates.append(item)
            if not candidates:
                continue
            best = min(candidates, key=self._relevance_sort_key)
            if best[0].id not in reserved:
                additions.append(best)
                reserved.add(best[0].id)

        if not additions:
            return ordered, reserved
        addition_ids = {item[0].id for item in additions}
        return additions + [item for item in ordered if item[0].id not in addition_ids], reserved
