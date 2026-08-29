"""Canonical semantic graph model for FeynMap.

The model is intentionally independent of Python, Django, and the physics notation.
Adapters translate source-language facts into this representation. Other layers
(querying, AI grounding, migration planning, visualization) consume it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .ontology import ConfidenceTier, EdgeKind, EvidenceKind, NodeKind, confidence_tier

SEMANTIC_SCHEMA = "feynmap.semantic_graph"
SEMANTIC_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class SourceLocation:
    path: str
    line: Optional[int] = None
    end_line: Optional[int] = None
    column: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    detector: str
    detail: str = ""
    location: Optional[SourceLocation] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind.value,
            "detector": self.detector,
            "confidence": round(float(self.confidence), 4),
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.location:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass
class SemanticNode:
    id: str
    name: str
    kind: NodeKind = NodeKind.UNKNOWN
    language: Optional[str] = None
    framework: Optional[str] = None
    qualified_name: Optional[str] = None
    location: Optional[SourceLocation] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.evidence:
            return 0.0
        return max(0.0, min(1.0, sum(item.confidence for item in self.evidence) / len(self.evidence)))

    @property
    def confidence_tier(self) -> ConfidenceTier:
        ai_only = bool(self.evidence) and all(item.kind == EvidenceKind.AI_INFERENCE for item in self.evidence)
        return confidence_tier(self.confidence, len(self.evidence), ai_only)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "confidence": round(self.confidence, 4),
            "confidence_tier": self.confidence_tier.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "attributes": self.attributes,
        }
        for key, value in (("language", self.language), ("framework", self.framework), ("qualified_name", self.qualified_name)):
            if value:
                payload[key] = value
        if self.location:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass
class SemanticEdge:
    id: str
    source: str
    target: str
    kind: EdgeKind
    confidence: float = 0.0
    evidence: List[Evidence] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def confidence_tier(self) -> ConfidenceTier:
        ai_only = bool(self.evidence) and all(item.kind == EvidenceKind.AI_INFERENCE for item in self.evidence)
        return confidence_tier(self.confidence, len(self.evidence), ai_only)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
            "confidence": round(float(self.confidence), 4),
            "confidence_tier": self.confidence_tier.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "attributes": self.attributes,
        }


@dataclass
class SemanticGraph:
    nodes: List[SemanticNode] = field(default_factory=list)
    edges: List[SemanticEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    diagnostics: Dict[str, List[str]] = field(default_factory=lambda: {"errors": [], "warnings": []})

    def __post_init__(self) -> None:
        self._reindex()

    def _reindex(self) -> None:
        self._nodes_by_id: Dict[str, SemanticNode] = {node.id: node for node in self.nodes}
        self._outgoing: Dict[str, List[SemanticEdge]] = {}
        self._incoming: Dict[str, List[SemanticEdge]] = {}
        for edge in self.edges:
            self._outgoing.setdefault(edge.source, []).append(edge)
            self._incoming.setdefault(edge.target, []).append(edge)

    def add_node(self, node: SemanticNode) -> None:
        if node.id in self._nodes_by_id:
            raise ValueError("duplicate semantic node id: %s" % node.id)
        self.nodes.append(node)
        self._nodes_by_id[node.id] = node

    def add_edge(self, edge: SemanticEdge) -> None:
        self.edges.append(edge)
        self._outgoing.setdefault(edge.source, []).append(edge)
        self._incoming.setdefault(edge.target, []).append(edge)

    def node(self, node_id: str) -> Optional[SemanticNode]:
        return self._nodes_by_id.get(node_id)

    def outgoing(self, node_id: str) -> List[SemanticEdge]:
        return list(self._outgoing.get(node_id, []))

    def incoming(self, node_id: str) -> List[SemanticEdge]:
        return list(self._incoming.get(node_id, []))

    def find(self, value: str) -> List[SemanticNode]:
        needle = value.casefold()
        exact: List[SemanticNode] = []
        partial: List[SemanticNode] = []
        for node in self.nodes:
            candidates = [node.id, node.name, node.qualified_name or ""]
            folded = [item.casefold() for item in candidates if item]
            if needle in folded:
                exact.append(node)
            elif any(needle in item for item in folded):
                partial.append(node)
        return exact + partial

    def validate(self) -> Dict[str, List[str]]:
        errors: List[str] = []
        warnings: List[str] = []
        ids = set(self._nodes_by_id)
        if len(ids) != len(self.nodes):
            errors.append("duplicate node ids are present")
        seen_edges = set()
        for edge in self.edges:
            if edge.id in seen_edges:
                errors.append("duplicate edge id: %s" % edge.id)
            seen_edges.add(edge.id)
            if edge.source not in ids:
                warnings.append("edge %s has missing source %s" % (edge.id, edge.source))
            if edge.target not in ids:
                warnings.append("edge %s has missing target %s" % (edge.id, edge.target))
            if not 0.0 <= edge.confidence <= 1.0:
                errors.append("edge %s confidence must be between 0 and 1" % edge.id)
        self.diagnostics = {"errors": errors, "warnings": warnings}
        return self.diagnostics

    def evidence_coverage(self) -> float:
        facts = len(self.nodes) + len(self.edges)
        if not facts:
            return 0.0
        evidenced = sum(1 for node in self.nodes if node.evidence) + sum(1 for edge in self.edges if edge.evidence)
        return evidenced / float(facts)

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "schema": SEMANTIC_SCHEMA,
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "metadata": {
                **self.metadata,
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "evidence_coverage": round(self.evidence_coverage(), 4),
            },
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "diagnostics": self.diagnostics,
        }
