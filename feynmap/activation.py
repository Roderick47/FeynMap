"""Sparse knowledge activation metrics and contracts.

This module is intentionally small. It does not replace FeynMap's semantic
graph, query layer, JEV-guided search, or context packer. It gives those pieces
one shared vocabulary for measuring whether the substrate is actually sparse.

The first invariant is simple: a large graph may be available, while only a
small grounded subset should be touched, activated, and ultimately delivered
to the downstream model for any one request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set

from .context import estimate_tokens
from .core import SemanticGraph
from .judgment.search import GuidedSearchResult


@dataclass(frozen=True)
class ActivationMetrics:
    """Observable sparsity metrics for one grounded search invocation."""

    total_graph_nodes: int
    candidate_nodes_seen: int
    activated_nodes: int
    delivered_nodes: int
    search_steps: int
    exhausted: bool
    truncated: bool
    routing_elapsed_ms: float = 0.0
    activated_context_tokens: int = 0

    @property
    def candidate_touch_ratio(self) -> float:
        if self.total_graph_nodes <= 0:
            return 0.0
        return float(self.candidate_nodes_seen) / float(self.total_graph_nodes)

    @property
    def knowledge_activation_ratio(self) -> float:
        if self.total_graph_nodes <= 0:
            return 0.0
        return float(self.activated_nodes) / float(self.total_graph_nodes)

    @property
    def delivery_to_activation_ratio(self) -> float:
        if self.activated_nodes <= 0:
            return 0.0
        return float(self.delivered_nodes) / float(self.activated_nodes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_graph_nodes": int(self.total_graph_nodes),
            "candidate_nodes_seen": int(self.candidate_nodes_seen),
            "activated_nodes": int(self.activated_nodes),
            "delivered_nodes": int(self.delivered_nodes),
            "search_steps": int(self.search_steps),
            "exhausted": bool(self.exhausted),
            "truncated": bool(self.truncated),
            "routing_elapsed_ms": round(float(self.routing_elapsed_ms), 6),
            "activated_context_tokens": int(self.activated_context_tokens),
            "candidate_touch_ratio": self.candidate_touch_ratio,
            "knowledge_activation_ratio": self.knowledge_activation_ratio,
            "delivery_to_activation_ratio": self.delivery_to_activation_ratio,
        }


def measure_guided_search(
    graph: SemanticGraph,
    result: GuidedSearchResult,
    delivered_node_ids: Optional[Iterable[str]] = None,
    routing_elapsed_seconds: float = 0.0,
) -> ActivationMetrics:
    """Measure one JEV-guided search without changing its retrieval behavior.

    candidate_nodes_seen counts distinct grounded candidates presented to the
    search policy. activated_nodes counts distinct nodes admitted into the
    selected traversal. delivered_nodes is supplied by the eventual context
    packer; until a dedicated minimal-sufficient packer lands, it defaults to
    the activated set.
    """

    candidate_ids: Set[str] = set()
    for step in result.trace:
        candidate_ids.update(step.candidates)

    activated_ids = {hit.node.id for hit in result.hits}

    if delivered_node_ids is None:
        delivered_ids = set(activated_ids)
    else:
        delivered_ids = {str(node_id) for node_id in delivered_node_ids}
        delivered_ids.intersection_update(activated_ids)

    compact_payload = {
        "nodes": [
            {
                "id": hit.node.id,
                "name": hit.node.name,
                "qualified_name": hit.node.qualified_name,
                "kind": hit.node.kind.value,
                "location": hit.node.location.to_dict() if hit.node.location else None,
                "confidence_tier": hit.node.confidence_tier.value,
            }
            for hit in result.hits
        ],
        "relationships": [
            {
                "source": edge.source,
                "relationship": edge.kind.value,
                "target": edge.target,
                "confidence_tier": edge.confidence_tier.value,
            }
            for edge in result.edges
        ],
    }
    activated_context_tokens = estimate_tokens(compact_payload)

    return ActivationMetrics(
        total_graph_nodes=len(graph.nodes),
        candidate_nodes_seen=len(candidate_ids),
        activated_nodes=len(activated_ids),
        delivered_nodes=len(delivered_ids),
        search_steps=len(result.trace),
        exhausted=result.exhausted,
        truncated=result.truncated,
        routing_elapsed_ms=max(0.0, float(routing_elapsed_seconds)) * 1000.0,
        activated_context_tokens=activated_context_tokens,
    )
