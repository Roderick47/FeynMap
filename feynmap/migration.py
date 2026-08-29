"""Migration planning primitives built on the semantic graph.

This module does not generate Rust yet. It identifies bounded migration units and
measures whether the graph is grounded enough for an automated migration agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Set

from .core import EdgeKind, EvidenceKind, NodeKind, SemanticGraph


@dataclass
class MigrationUnit:
    id: str
    seed: str
    members: List[str]
    incoming_boundaries: List[str]
    outgoing_boundaries: List[str]
    confidence: float
    risk: str


class MigrationPlanner:
    COHESIVE_EDGES = {EdgeKind.CALLS, EdgeKind.DEPENDS_ON, EdgeKind.USES_DATA, EdgeKind.SERIALIZES, EdgeKind.VALIDATES, EdgeKind.PERSISTS}
    SEED_KINDS = {NodeKind.HANDLER, NodeKind.SERVICE, NodeKind.DATA_MODEL}

    def __init__(self, graph: SemanticGraph) -> None:
        self.graph = graph

    def assess(self, target: str = "rust") -> Dict[str, Any]:
        if target.lower() != "rust":
            raise ValueError("only Rust planning is currently defined")
        edge_confidence = sum(edge.confidence for edge in self.graph.edges) / float(max(len(self.graph.edges), 1))
        ai_inferred = sum(1 for edge in self.graph.edges if edge.evidence and all(item.kind == EvidenceKind.AI_INFERENCE for item in edge.evidence))
        unknown = sum(1 for node in self.graph.nodes if node.kind == NodeKind.UNKNOWN)
        readiness = self.graph.evidence_coverage() * 0.45 + edge_confidence * 0.35 + (1.0 - min(1.0, unknown / float(max(len(self.graph.nodes), 1)))) * 0.20
        return {
            "target": "rust",
            "readiness_score": round(readiness, 4),
            "evidence_coverage": round(self.graph.evidence_coverage(), 4),
            "average_edge_confidence": round(edge_confidence, 4),
            "unknown_node_count": unknown,
            "ai_only_edge_count": ai_inferred,
            "note": "Readiness measures graph grounding and structural clarity, not guaranteed source-to-Rust convertibility.",
        }

    def build_units(self, max_nodes: int = 25) -> List[MigrationUnit]:
        max_nodes = max(2, int(max_nodes))
        assigned: Set[str] = set()
        units: List[MigrationUnit] = []
        seeds = [node for node in self.graph.nodes if node.kind in self.SEED_KINDS]
        seeds.extend(node for node in self.graph.nodes if node not in seeds)
        for seed in seeds:
            if seed.id in assigned:
                continue
            members = self._grow(seed.id, assigned, max_nodes)
            if not members:
                continue
            assigned.update(members)
            incoming, outgoing = self._boundaries(members)
            confidences = [edge.confidence for edge in self.graph.edges if edge.source in members and edge.target in members and edge.kind in self.COHESIVE_EDGES]
            confidence = sum(confidences) / float(max(len(confidences), 1)) if confidences else seed.confidence
            risk = "low" if confidence >= 0.9 and len(incoming) + len(outgoing) <= 6 else "medium" if confidence >= 0.7 else "high"
            units.append(MigrationUnit("unit-%03d" % (len(units) + 1), seed.id, sorted(members), sorted(incoming), sorted(outgoing), round(confidence, 4), risk))
        return units

    def plan(self, target: str = "rust", max_nodes: int = 25) -> Dict[str, Any]:
        return {"assessment": self.assess(target), "units": [asdict(unit) for unit in self.build_units(max_nodes=max_nodes)]}

    def _grow(self, seed: str, assigned: Set[str], max_nodes: int) -> Set[str]:
        members: Set[str] = set()
        queue = [seed]
        while queue and len(members) < max_nodes:
            current = queue.pop(0)
            if current in assigned or current in members:
                continue
            members.add(current)
            for edge in self.graph.outgoing(current) + self.graph.incoming(current):
                if edge.kind not in self.COHESIVE_EDGES or edge.confidence < 0.60:
                    continue
                neighbor = edge.target if edge.source == current else edge.source
                if neighbor not in members and neighbor not in assigned:
                    queue.append(neighbor)
        return members

    def _boundaries(self, members: Set[str]):
        incoming: Set[str] = set()
        outgoing: Set[str] = set()
        for edge in self.graph.edges:
            if edge.source not in members and edge.target in members:
                incoming.add(edge.source)
            elif edge.source in members and edge.target not in members:
                outgoing.add(edge.target)
        return incoming, outgoing
