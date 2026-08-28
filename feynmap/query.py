"""Grounded query API for humans and AI coding agents."""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set

from .core import EdgeKind, SemanticGraph, SemanticNode


class FeynMapQuery:
    def __init__(self, graph: SemanticGraph) -> None:
        self.graph = graph

    def resolve(self, symbol: str) -> SemanticNode:
        matches = self.graph.find(symbol)
        if not matches:
            raise KeyError("symbol not found: %s" % symbol)
        if len(matches) > 1 and matches[0].name.casefold() != symbol.casefold() and matches[0].id.casefold() != symbol.casefold():
            raise KeyError("symbol is ambiguous: %s; matches=%s" % (symbol, ", ".join(node.id for node in matches[:8])))
        return matches[0]

    def dependencies(self, symbol: str, depth: int = 1) -> Dict[str, Any]:
        return self._walk(self.resolve(symbol).id, outgoing=True, depth=depth)

    def callers(self, symbol: str, depth: int = 1) -> Dict[str, Any]:
        return self._walk(self.resolve(symbol).id, outgoing=False, depth=depth)

    def impact(self, symbol: str, depth: int = 4) -> Dict[str, Any]:
        return self.callers(symbol, depth=depth)

    def context_bundle(self, symbol: str, depth: int = 2) -> Dict[str, Any]:
        node = self.resolve(symbol)
        return {
            "symbol": node.to_dict(),
            "dependencies": self.dependencies(node.id, depth=depth),
            "callers": self.callers(node.id, depth=depth),
            "grounding": {
                "rule": "Treat evidenced graph facts as grounding. Treat missing relationships as unknown, not false, unless analysis is complete for that relation type.",
                "graph_evidence_coverage": round(self.graph.evidence_coverage(), 4),
            },
        }

    def validate_claim(self, source: str, target: str, relationship: Optional[str] = None) -> Dict[str, Any]:
        source_node = self.resolve(source)
        target_node = self.resolve(target)
        requested_kind = None
        if relationship:
            normalized = relationship.strip().lower()
            try:
                requested_kind = EdgeKind(normalized)
            except ValueError:
                aliases = {"call": EdgeKind.CALLS, "dependency": EdgeKind.DEPENDS_ON, "uses": EdgeKind.USES_DATA}
                requested_kind = aliases.get(normalized)
                if requested_kind is None:
                    raise ValueError("unknown relationship: %s" % relationship)

        matches = [edge for edge in self.graph.outgoing(source_node.id) if edge.target == target_node.id and (requested_kind is None or edge.kind == requested_kind)]
        if matches:
            strongest = max(matches, key=lambda edge: edge.confidence)
            return {
                "status": strongest.confidence_tier.value,
                "supported": True,
                "claim": {"source": source_node.id, "relationship": requested_kind.value if requested_kind else None, "target": target_node.id},
                "evidence": [edge.to_dict() for edge in matches],
            }

        return {
            "status": "unsupported",
            "supported": False,
            "claim": {"source": source_node.id, "relationship": requested_kind.value if requested_kind else None, "target": target_node.id},
            "note": "No matching graph edge was found. This means FeynMap has no current evidence for the claim; it does not prove the relationship is impossible.",
            "nearby_relationships": [edge.to_dict() for edge in self.graph.outgoing(source_node.id)[:10]],
        }

    def _walk(self, start_id: str, outgoing: bool, depth: int) -> Dict[str, Any]:
        depth = max(0, int(depth))
        queue = deque([(start_id, 0)])
        seen_nodes: Set[str] = {start_id}
        seen_edges: Set[str] = set()
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            candidates = self.graph.outgoing(current) if outgoing else self.graph.incoming(current)
            for edge in candidates:
                if edge.id not in seen_edges:
                    seen_edges.add(edge.id)
                    edges.append(edge.to_dict())
                neighbor = edge.target if outgoing else edge.source
                if neighbor in seen_nodes:
                    continue
                seen_nodes.add(neighbor)
                node = self.graph.node(neighbor)
                if node:
                    nodes.append(node.to_dict())
                    queue.append((neighbor, current_depth + 1))
        return {"root": start_id, "direction": "outgoing" if outgoing else "incoming", "depth": depth, "nodes": nodes, "edges": edges}
