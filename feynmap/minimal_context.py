"""Minimal sufficient downstream context over an activated FeynMap search.

S2 decides what knowledge to activate. S3 decides what subset of that activated,
grounded subgraph should be delivered to a downstream model.

The packer never invents facts. Selected relationships are stored semantic
edges and are admitted together with their endpoints. Node/edge evidence is
compacted using the same transport-neutral representation as stored context.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .context import _compact_edge, _compact_node, estimate_tokens
from .core import EdgeKind, SemanticEdge, SemanticGraph, SemanticNode
from .core.model import TIER_RANK
from .judgment.search import GuidedSearchResult, SearchHit, _edge_search_priority


_DELIVERY_EDGE_PRIORITY = {
    EdgeKind.RENDERS: 1.00,
    EdgeKind.LOADS: 1.00,
    EdgeKind.REQUESTS: 1.00,
    EdgeKind.INVOKES: 1.00,
    EdgeKind.CONNECTS_TO: 1.00,
    EdgeKind.FLOWS_TO: 1.00,
    EdgeKind.ROUTES_TO: 1.00,
    EdgeKind.SPAWNS: 0.95,
    EdgeKind.EMITS: 0.95,
    EdgeKind.SUBSCRIBES: 0.95,
    EdgeKind.CALLS: 0.75,
    EdgeKind.USES_DATA: 0.70,
    EdgeKind.READS: 0.70,
    EdgeKind.WRITES: 0.70,
    EdgeKind.MUTATES: 0.70,
    EdgeKind.PERSISTS: 0.70,
    EdgeKind.VALIDATES: 0.65,
    EdgeKind.SERIALIZES: 0.65,
    EdgeKind.DEPENDS_ON: 0.55,
    EdgeKind.AWAITS: 0.55,
    EdgeKind.CREATES: 0.50,
    EdgeKind.DELETES: 0.50,
    EdgeKind.EXTENDS: 0.35,
    EdgeKind.IMPORTS: 0.25,
    EdgeKind.CONTAINS: 0.15,
    EdgeKind.OWNS: 0.15,
}


def _delivery_edge_priority(edge: SemanticEdge) -> float:
    return float(_DELIVERY_EDGE_PRIORITY.get(edge.kind, 0.50))


def _tokens(value: str) -> Set[str]:
    cleaned = "".join(
        character.casefold() if character.isalnum() else " "
        for character in str(value or "")
    )
    return {token for token in cleaned.split() if len(token) >= 3}


def _flatten(value: Any, depth: int = 0) -> Iterable[str]:
    if depth > 2:
        return
    if isinstance(value, (str, int, float, bool)):
        yield str(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            for text in _flatten(item, depth + 1):
                yield text
        return
    if isinstance(value, (list, tuple, set)):
        for item in list(value)[:24]:
            for text in _flatten(item, depth + 1):
                yield text


def _node_terms(node: SemanticNode) -> Set[str]:
    values = [
        node.id,
        node.name,
        node.qualified_name or "",
        node.kind.value,
        node.language or "",
        node.framework or "",
        node.location.path if node.location else "",
    ]
    values.extend(_flatten(node.attributes))
    return _tokens(" ".join(values))


@dataclass(frozen=True)
class MinimalContextBudget:
    max_tokens: int = 1800
    max_nodes: int = 24
    max_edges: int = 24

    def normalized(self) -> "MinimalContextBudget":
        return MinimalContextBudget(
            max_tokens=max(128, int(self.max_tokens)),
            max_nodes=max(1, int(self.max_nodes)),
            max_edges=max(0, int(self.max_edges)),
        )


@dataclass(frozen=True)
class MinimalContextResult:
    payload: Mapping[str, Any]
    selected_node_ids: Sequence[str]
    selected_edge_ids: Sequence[str]
    activated_tokens: int
    delivered_tokens: int
    activated_nodes: int
    delivered_nodes: int

    @property
    def token_compression_ratio(self) -> float:
        if self.activated_tokens <= 0:
            return 1.0
        return float(self.delivered_tokens) / float(self.activated_tokens)

    @property
    def node_compression_ratio(self) -> float:
        if self.activated_nodes <= 0:
            return 1.0
        return float(self.delivered_nodes) / float(self.activated_nodes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload": dict(self.payload),
            "selected_node_ids": list(self.selected_node_ids),
            "selected_edge_ids": list(self.selected_edge_ids),
            "metrics": {
                "activated_tokens": int(self.activated_tokens),
                "delivered_tokens": int(self.delivered_tokens),
                "token_compression_ratio": self.token_compression_ratio,
                "tokens_saved": max(0, int(self.activated_tokens - self.delivered_tokens)),
                "activated_nodes": int(self.activated_nodes),
                "delivered_nodes": int(self.delivered_nodes),
                "node_compression_ratio": self.node_compression_ratio,
            },
        }


class MinimalContextPacker:
    """Select a compact, evidence-preserving subgraph from activated knowledge."""

    def __init__(self, graph: SemanticGraph) -> None:
        self.graph = graph

    def pack(
        self,
        result: GuidedSearchResult,
        *,
        budget: Optional[MinimalContextBudget] = None,
    ) -> MinimalContextResult:
        budget = (budget or MinimalContextBudget()).normalized()
        hit_by_id: Dict[str, SearchHit] = {hit.node.id: hit for hit in result.hits}
        activated_ids = set(hit_by_id)
        edge_by_id = {edge.id: edge for edge in result.edges}
        activated_edges = [
            edge
            for edge in result.edges
            if edge.source in activated_ids and edge.target in activated_ids
        ]

        activated_payload = self._payload(
            result,
            [hit.node.id for hit in result.hits],
            [edge.id for edge in activated_edges],
            [node.id for node in result.roots if node.id in activated_ids],
        )
        activated_tokens = estimate_tokens(activated_payload)

        if not result.hits:
            payload = self._payload(result, [], [], [])
            delivered_tokens = estimate_tokens(payload)
            return MinimalContextResult(
                payload=payload,
                selected_node_ids=(),
                selected_edge_ids=(),
                activated_tokens=activated_tokens,
                delivered_tokens=delivered_tokens,
                activated_nodes=0,
                delivered_nodes=0,
            )

        node_scores = self._node_scores(result, hit_by_id, activated_edges)
        edge_scores = self._edge_scores(activated_edges, node_scores)

        primary_roots = [node.id for node in result.roots if node.id in activated_ids]
        if not primary_roots:
            primary_roots = [result.hits[0].node.id]

        selected_nodes: Set[str] = set()
        selected_edges: Set[str] = set()
        anchors: List[str] = []

        # Preserve the strongest original root. Additional roots/region seeds
        # compete normally and are delivered only if they add useful evidence.
        first_root = primary_roots[0]
        if self._try_add(
            result,
            budget,
            selected_nodes,
            selected_edges,
            anchors,
            [first_root],
            [],
        ):
            anchors.append(first_root)
        else:
            # The compact root should fit all supported budgets; fail clearly
            # rather than returning a misleading empty context.
            raise ValueError("minimal context budget is too small for the primary grounded root")

        # Reserve a few delivery-critical boundary continuations. Unlike
        # search-time priority, delivery priority demotes generic inheritance
        # and containment. Selection is frontier-aware so the reserve tends to
        # continue an already grounded path instead of opening arbitrary
        # disconnected high-confidence edges.
        remaining_boundary = {
            edge.id: edge
            for edge in activated_edges
            if _delivery_edge_priority(edge) >= 0.90
        }
        for _ in range(4):
            candidates: List[Tuple[float, str, SemanticEdge]] = []
            for edge_id, edge in remaining_boundary.items():
                nodes = {edge.source, edge.target}
                connectivity = 1.0 if nodes.intersection(selected_nodes) else 0.0
                source = self.graph.node(edge.source)
                target = self.graph.node(edge.target)
                cross_language = bool(
                    source is not None
                    and target is not None
                    and source.language
                    and target.language
                    and source.language != target.language
                )
                file_novelty = 0.0
                selected_paths = {
                    self.graph.node(node_id).location.path
                    for node_id in selected_nodes
                    if self.graph.node(node_id) is not None
                    and self.graph.node(node_id).location is not None
                }
                endpoint_paths = {
                    node.location.path
                    for node in (source, target)
                    if node is not None and node.location is not None
                }
                if endpoint_paths - selected_paths:
                    file_novelty = 0.45
                score = (
                    2.0 * _delivery_edge_priority(edge)
                    + 0.35 * (
                        node_scores.get(edge.source, 0.0)
                        + node_scores.get(edge.target, 0.0)
                    )
                    + 1.35 * connectivity
                    + file_novelty
                    + (0.55 if cross_language else 0.0)
                )
                candidates.append((score, edge_id, edge))
            candidates.sort(key=lambda item: (-item[0], item[1]))
            admitted = False
            for _, edge_id, edge in candidates:
                nodes = {edge.source, edge.target}
                candidate_anchors = list(anchors)
                if not nodes.intersection(selected_nodes):
                    anchor_id = max(
                        nodes,
                        key=lambda item: (node_scores.get(item, 0.0), item),
                    )
                    if anchor_id not in candidate_anchors:
                        candidate_anchors.append(anchor_id)
                if self._fits(
                    result,
                    budget,
                    selected_nodes | nodes,
                    selected_edges | {edge.id},
                    candidate_anchors,
                ):
                    selected_nodes.update(nodes)
                    selected_edges.add(edge.id)
                    anchors[:] = candidate_anchors
                    admitted = True
                    del remaining_boundary[edge_id]
                    break
                del remaining_boundary[edge_id]
            if not admitted:
                break

        # Preserve semantic diversity across source files. Activated search has
        # already paid to discover these nodes; S3 should not spend its entire
        # delivery budget on several variants from one file while dropping the
        # best representative of another strong file/region.
        file_groups: Dict[str, List[str]] = {}
        hit_order = {hit.node.id: index for index, hit in enumerate(result.hits)}
        for node_id in activated_ids - selected_nodes:
            node = self.graph.node(node_id)
            if node is None or node.location is None or not node.location.path:
                continue
            file_groups.setdefault(node.location.path, []).append(node_id)

        file_candidates: List[Tuple[float, str, str]] = []
        total_hits = max(1, len(result.hits))
        query_terms = _tokens(result.query)
        for path, node_ids in file_groups.items():
            representative = max(
                node_ids,
                key=lambda item: (
                    node_scores.get(item, 0.0),
                    -hit_order.get(item, total_hits),
                    item,
                ),
            )
            incident_boundary = 0.0
            for edge in activated_edges:
                if representative not in {edge.source, edge.target}:
                    continue
                incident_boundary = max(
                    incident_boundary,
                    _edge_search_priority(edge),
                )
            order_bonus = 1.0 - (
                float(hit_order.get(representative, total_hits))
                / float(total_hits)
            )
            file_terms: Set[str] = set()
            for item in node_ids:
                node = self.graph.node(item)
                if node is not None:
                    file_terms.update(_node_terms(node))
            file_overlap = (
                float(len(query_terms & file_terms)) / float(len(query_terms))
                if query_terms
                else 0.0
            )
            file_score = (
                node_scores.get(representative, 0.0)
                + (0.45 * order_bonus)
                + (0.45 * incident_boundary)
                + (2.0 * file_overlap)
            )
            file_candidates.append((file_score, path, representative))

        file_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        diversity_slots = min(6, max(2, budget.max_nodes // 3))
        admitted_files = 0
        represented_paths = {
            self.graph.node(node_id).location.path
            for node_id in selected_nodes
            if self.graph.node(node_id) is not None
            and self.graph.node(node_id).location is not None
        }
        for _, path, node_id in file_candidates:
            if admitted_files >= diversity_slots:
                break
            if path in represented_paths:
                continue
            closure_nodes, closure_edges, anchor_candidate = self._path_closure(
                node_id,
                hit_by_id,
                edge_by_id,
                selected_nodes,
            )
            candidate_anchors = list(anchors)
            if anchor_candidate and anchor_candidate not in candidate_anchors:
                candidate_anchors.append(anchor_candidate)
            if self._fits(
                result,
                budget,
                selected_nodes | set(closure_nodes),
                selected_edges | set(closure_edges),
                candidate_anchors,
            ):
                selected_nodes.update(closure_nodes)
                selected_edges.update(closure_edges)
                anchors[:] = candidate_anchors
                represented_paths.add(path)
                admitted_files += 1

        ranked_nodes = sorted(
            activated_ids - selected_nodes,
            key=lambda node_id: (-node_scores.get(node_id, 0.0), node_id),
        )

        # Then admit high-value nodes with their search-parent path. This keeps
        # the explanation/evidence chain whenever the search result records one.
        for node_id in ranked_nodes:
            closure_nodes, closure_edges, anchor_candidate = self._path_closure(
                node_id,
                hit_by_id,
                edge_by_id,
                selected_nodes,
            )
            candidate_anchors = list(anchors)
            if anchor_candidate and anchor_candidate not in candidate_anchors:
                candidate_anchors.append(anchor_candidate)
            if self._fits(
                result,
                budget,
                selected_nodes | set(closure_nodes),
                selected_edges | set(closure_edges),
                candidate_anchors,
            ):
                selected_nodes.update(closure_nodes)
                selected_edges.update(closure_edges)
                anchors[:] = candidate_anchors

        # Then add high-value relationships atomically with endpoints. This can
        # preserve a useful cross-boundary fact even if one endpoint ranked just
        # below the node cutoff.
        ranked_edges = sorted(
            activated_edges,
            key=lambda edge: (-edge_scores.get(edge.id, 0.0), edge.id),
        )
        for edge in ranked_edges:
            if edge.id in selected_edges:
                continue
            nodes = {edge.source, edge.target}
            if len(selected_nodes | nodes) > budget.max_nodes:
                continue
            if len(selected_edges) + 1 > budget.max_edges:
                break
            candidate_anchors = list(anchors)
            # If neither endpoint connects to existing selected context, retain
            # the stronger endpoint as an explicit secondary grounded anchor.
            if not nodes.intersection(selected_nodes):
                anchor_id = max(nodes, key=lambda item: (node_scores.get(item, 0.0), item))
                if anchor_id not in candidate_anchors:
                    candidate_anchors.append(anchor_id)
            if self._fits(
                result,
                budget,
                selected_nodes | nodes,
                selected_edges | {edge.id},
                candidate_anchors,
            ):
                selected_nodes.update(nodes)
                selected_edges.add(edge.id)
                anchors[:] = candidate_anchors

        payload = self._payload(
            result,
            sorted(selected_nodes, key=lambda item: (-node_scores.get(item, 0.0), item)),
            sorted(selected_edges, key=lambda item: (-edge_scores.get(item, 0.0), item)),
            anchors,
        )
        delivered_tokens = estimate_tokens(payload)
        return MinimalContextResult(
            payload=payload,
            selected_node_ids=tuple(
                sorted(selected_nodes, key=lambda item: (-node_scores.get(item, 0.0), item))
            ),
            selected_edge_ids=tuple(
                sorted(selected_edges, key=lambda item: (-edge_scores.get(item, 0.0), item))
            ),
            activated_tokens=activated_tokens,
            delivered_tokens=delivered_tokens,
            activated_nodes=len(activated_ids),
            delivered_nodes=len(selected_nodes),
        )

    def _node_scores(
        self,
        result: GuidedSearchResult,
        hit_by_id: Mapping[str, SearchHit],
        edges: Sequence[SemanticEdge],
    ) -> Dict[str, float]:
        query_terms = _tokens(result.query)
        document_frequency: Dict[str, int] = {}
        terms_by_id: Dict[str, Set[str]] = {}
        for node_id, hit in hit_by_id.items():
            terms = _node_terms(hit.node)
            terms_by_id[node_id] = terms
            for term in terms:
                document_frequency[term] = document_frequency.get(term, 0) + 1

        count = max(1, len(hit_by_id))

        def idf(term: str) -> float:
            return math.log((count + 1.0) / (document_frequency.get(term, 0) + 1.0)) + 1.0

        denominator = sum(idf(term) for term in query_terms) or 1.0
        degree: Dict[str, float] = {node_id: 0.0 for node_id in hit_by_id}
        for edge in edges:
            weight = _edge_search_priority(edge)
            degree[edge.source] = degree.get(edge.source, 0.0) + weight
            degree[edge.target] = degree.get(edge.target, 0.0) + weight
        max_degree = max(degree.values(), default=1.0) or 1.0

        primary_root = result.roots[0].id if result.roots else None
        scores: Dict[str, float] = {}
        for node_id, hit in hit_by_id.items():
            overlap = sum(
                idf(term)
                for term in query_terms
                if term in terms_by_id.get(node_id, set())
            ) / denominator
            probability = max(0.0, min(1.0, float(hit.search_probability or 0.0)))
            seed = max(0.0, min(1.0, float(hit.seed_score or 0.0)))
            path = max(0.0, min(1.0, float(hit.path_score or 0.0)))
            confidence = TIER_RANK.get(hit.node.confidence_tier, 0) / 3.0
            structural = degree.get(node_id, 0.0) / max_degree
            depth = max(0, int(hit.depth))
            score = (
                (2.6 * overlap)
                + (0.8 * structural)
                + (0.5 * confidence)
                + (0.5 * probability)
                + (0.3 * seed)
                + (0.3 * path)
                + (0.35 / (1.0 + depth))
                + (0.8 if node_id == primary_root else 0.0)
            )
            scores[node_id] = score
        return scores

    @staticmethod
    def _edge_scores(
        edges: Sequence[SemanticEdge],
        node_scores: Mapping[str, float],
    ) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for edge in edges:
            endpoint = 0.5 * (
                node_scores.get(edge.source, 0.0)
                + node_scores.get(edge.target, 0.0)
            )
            evidence = TIER_RANK.get(edge.confidence_tier, 0) / 3.0
            scores[edge.id] = (
                1.6 * _delivery_edge_priority(edge)
                + 0.5 * endpoint
                + 0.5 * evidence
                + 0.25 * float(edge.confidence)
            )
        return scores

    def _path_closure(
        self,
        node_id: str,
        hit_by_id: Mapping[str, SearchHit],
        edge_by_id: Mapping[str, SemanticEdge],
        selected_nodes: Set[str],
    ) -> Tuple[List[str], List[str], Optional[str]]:
        nodes: List[str] = []
        edges: List[str] = []
        current = node_id
        seen: Set[str] = set()
        anchor: Optional[str] = None
        while current not in seen and current not in selected_nodes:
            seen.add(current)
            hit = hit_by_id.get(current)
            if hit is None:
                break
            nodes.append(current)
            if hit.parent_id is None:
                anchor = current
                break
            if hit.via_edge_id and hit.via_edge_id in edge_by_id:
                edges.append(hit.via_edge_id)
            current = hit.parent_id
        return nodes, edges, anchor

    def _try_add(
        self,
        result: GuidedSearchResult,
        budget: MinimalContextBudget,
        selected_nodes: Set[str],
        selected_edges: Set[str],
        anchors: Sequence[str],
        nodes: Sequence[str],
        edges: Sequence[str],
    ) -> bool:
        next_nodes = selected_nodes | set(nodes)
        next_edges = selected_edges | set(edges)
        if len(next_nodes) > budget.max_nodes or len(next_edges) > budget.max_edges:
            return False
        return self._fits(
            result,
            budget,
            next_nodes,
            next_edges,
            anchors,
        )

    def _fits(
        self,
        result: GuidedSearchResult,
        budget: MinimalContextBudget,
        node_ids: Set[str],
        edge_ids: Set[str],
        anchors: Sequence[str],
    ) -> bool:
        if len(node_ids) > budget.max_nodes or len(edge_ids) > budget.max_edges:
            return False
        payload = self._payload(
            result,
            sorted(node_ids),
            sorted(edge_ids),
            list(anchors),
        )
        return estimate_tokens(payload) <= budget.max_tokens

    def _payload(
        self,
        result: GuidedSearchResult,
        node_ids: Sequence[str],
        edge_ids: Sequence[str],
        anchors: Sequence[str],
    ) -> Dict[str, Any]:
        nodes = [
            self.graph.node(node_id)
            for node_id in node_ids
            if self.graph.node(node_id) is not None
        ]
        edge_map = {edge.id: edge for edge in result.edges}
        edges = [edge_map[edge_id] for edge_id in edge_ids if edge_id in edge_map]
        return {
            "query": result.query,
            "anchors": list(anchors),
            "nodes": [_compact_node(node) for node in nodes],
            "relationships": [_compact_edge(edge) for edge in edges],
            "grounding": {
                "known": "Every included node and relationship comes from the activated FeynMap semantic graph.",
                "unknown": "Omitted activated facts are not false; they were excluded by minimal-context selection.",
                "selection": "Post-activation relevance + structural scoring with atomic relationship/endpoints and search-parent path preservation.",
            },
        }
