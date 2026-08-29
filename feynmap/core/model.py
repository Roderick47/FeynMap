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


def _diagnostic_merge(left: List[str], right: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in list(left) + list(right):
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


@dataclass(frozen=True)
class SourceLocation:
    path: str
    line: Optional[int] = None
    end_line: Optional[int] = None
    column: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SourceLocation":
        return cls(
            path=str(payload.get("path", "")),
            line=payload.get("line"),
            end_line=payload.get("end_line"),
            column=payload.get("column"),
        )


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

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Evidence":
        location_payload = payload.get("location")
        return cls(
            kind=EvidenceKind(str(payload.get("kind", EvidenceKind.STATIC.value))),
            detector=str(payload.get("detector", "")),
            detail=str(payload.get("detail", "")),
            location=SourceLocation.from_dict(location_payload) if isinstance(location_payload, dict) else None,
            confidence=float(payload.get("confidence", 1.0)),
        )


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

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SemanticNode":
        location_payload = payload.get("location")
        evidence_payload = payload.get("evidence", [])
        return cls(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", "")),
            kind=NodeKind(str(payload.get("kind", NodeKind.UNKNOWN.value))),
            language=payload.get("language"),
            framework=payload.get("framework"),
            qualified_name=payload.get("qualified_name"),
            location=SourceLocation.from_dict(location_payload) if isinstance(location_payload, dict) else None,
            attributes=dict(payload.get("attributes") or {}),
            evidence=[Evidence.from_dict(item) for item in evidence_payload if isinstance(item, dict)],
        )


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

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SemanticEdge":
        evidence_payload = payload.get("evidence", [])
        return cls(
            id=str(payload.get("id", "")),
            source=str(payload.get("source", "")),
            target=str(payload.get("target", "")),
            kind=EdgeKind(str(payload.get("kind", EdgeKind.RELATED_TO.value))),
            confidence=float(payload.get("confidence", 0.0)),
            evidence=[Evidence.from_dict(item) for item in evidence_payload if isinstance(item, dict)],
            attributes=dict(payload.get("attributes") or {}),
        )


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
        previous = {
            "errors": list(self.diagnostics.get("errors", [])),
            "warnings": list(self.diagnostics.get("warnings", [])),
        }
        structural = self.validate()
        self.diagnostics = {
            "errors": _diagnostic_merge(previous["errors"], structural.get("errors", [])),
            "warnings": _diagnostic_merge(previous["warnings"], structural.get("warnings", [])),
        }
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

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SemanticGraph":
        schema = payload.get("schema")
        if schema and schema != SEMANTIC_SCHEMA:
            raise ValueError("unsupported semantic graph schema: %s" % schema)
        schema_version = payload.get("schema_version")
        if schema_version and schema_version != SEMANTIC_SCHEMA_VERSION:
            raise ValueError(
                "unsupported semantic graph schema version %s; expected %s"
                % (schema_version, SEMANTIC_SCHEMA_VERSION)
            )

        metadata = dict(payload.get("metadata") or {})
        for derived in ("node_count", "edge_count", "evidence_coverage"):
            metadata.pop(derived, None)
        nodes_payload = payload.get("nodes", [])
        edges_payload = payload.get("edges", [])
        diagnostics_payload = payload.get("diagnostics") or {}
        graph = cls(
            nodes=[SemanticNode.from_dict(item) for item in nodes_payload if isinstance(item, dict)],
            edges=[SemanticEdge.from_dict(item) for item in edges_payload if isinstance(item, dict)],
            metadata=metadata,
        )
        structural = graph.validate()
        graph.diagnostics = {
            "errors": _diagnostic_merge(list(diagnostics_payload.get("errors", [])), structural.get("errors", [])),
            "warnings": _diagnostic_merge(list(diagnostics_payload.get("warnings", [])), structural.get("warnings", [])),
        }
        return graph
