"""Python adapter backed by FeynMap's mature V2 extractor.

This bridge keeps the existing Python/Django/Flask/FastAPI analyzer useful while
translating its output into the new language-neutral semantic core.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from .base import LanguageAdapter

LEGACY_NODE_MAP = {
    "VERTEX": NodeKind.HANDLER,
    "PARTICLE": NodeKind.DATA_MODEL,
    "TRANSFORM": NodeKind.TRANSFORMER,
    "MEDIATOR": NodeKind.SERVICE,
    "FRONTEND": NodeKind.UI_SURFACE,
    "JAVASCRIPT": NodeKind.CLIENT_LOGIC,
    "AJAX": NodeKind.EXTERNAL_SYSTEM,
    "DEPENDENCY": NodeKind.EXTERNAL_SYSTEM,
    "UNKNOWN": NodeKind.UNKNOWN,
}

LEGACY_EDGE_MAP = {
    "CALL": EdgeKind.CALLS,
    "CONTAINS": EdgeKind.CONTAINS,
    "PARTICLE_ENTANGLEMENT": EdgeKind.USES_DATA,
    "SERIALIZER_ENTANGLEMENT": EdgeKind.SERIALIZES,
    "AJAX": EdgeKind.REQUESTS,
    "EVENT": EdgeKind.EMITS,
    "OBSERVATION": EdgeKind.OBSERVES,
    "VIRTUAL": EdgeKind.RELATED_TO,
    "DEPENDENCY": EdgeKind.DEPENDS_ON,
}


class PythonAdapter(LanguageAdapter):
    name = "python"
    extensions = (".py",)

    def detect_score(self, project_path: Path) -> float:
        files = 0
        python_files = 0
        excluded = {".git", ".venv", "venv", "node_modules", "__pycache__"}
        for path in project_path.rglob("*"):
            if not path.is_file() or any(part in excluded for part in path.parts):
                continue
            files += 1
            if path.suffix == ".py":
                python_files += 1
        if python_files == 0:
            return 0.0
        ratio = python_files / float(max(files, 1))
        manifest_bonus = 0.2 if any((project_path / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")) else 0.0
        return min(1.0, 0.55 + (ratio * 0.25) + manifest_bonus)

    def analyze(self, project_path: Path, framework: str = "auto") -> SemanticGraph:
        try:
            from feyn_parser import FeynExtractor
        except ImportError as exc:
            raise RuntimeError("The bundled V2 Python extractor is unavailable.") from exc

        extractor = FeynExtractor(str(project_path), framework=framework)
        legacy_graph = extractor.scan()
        resolved_framework = getattr(getattr(extractor, "config", None), "framework_name", None)
        return legacy_graph_to_semantic(legacy_graph, framework=resolved_framework or framework)


def legacy_graph_to_semantic(legacy_graph: Dict[str, Any], framework: Optional[str] = None) -> SemanticGraph:
    nodes: List[SemanticNode] = []
    edges: List[SemanticEdge] = []

    for raw in legacy_graph.get("nodes", []):
        location = _node_location(raw)
        legacy_type = str(raw.get("type") or "UNKNOWN")
        evidence = _evidence_list(raw.get("evidence"), location, "legacy.python.node")
        if not evidence:
            evidence = [
                Evidence(
                    EvidenceKind.STATIC if location else EvidenceKind.HEURISTIC,
                    "legacy.python.node",
                    "Parsed source symbol" if location else "Legacy parser classification",
                    location,
                    0.98 if location else 0.70,
                )
            ]
        attributes = dict(raw.get("attributes") or {})
        attributes.setdefault("legacy", {})["node_type"] = legacy_type
        if raw.get("metadata"):
            attributes["physics"] = raw.get("metadata")

        nodes.append(
            SemanticNode(
                id=str(raw.get("id")),
                name=str(raw.get("name") or raw.get("id")),
                qualified_name=raw.get("qualified_name"),
                kind=LEGACY_NODE_MAP.get(legacy_type, NodeKind.UNKNOWN),
                language=raw.get("language") or "python",
                framework=framework if framework not in {None, "auto", "generic"} else None,
                location=location,
                attributes=attributes,
                evidence=evidence,
            )
        )

    locations = {node.id: node.location for node in nodes}
    for index, raw in enumerate(legacy_graph.get("edges", [])):
        source = str(raw.get("source"))
        target = str(raw.get("target"))
        legacy_type = str(raw.get("type") or "DEPENDENCY")
        location = _edge_location(raw) or locations.get(source)
        evidence = _evidence_list(raw.get("evidence"), location, "legacy.python.edge")
        raw_confidence = raw.get("confidence")
        confidence = max(0.0, min(1.0, float(raw_confidence))) if raw_confidence is not None else (0.90 if location or evidence else 0.65)
        if not evidence:
            evidence = [
                Evidence(
                    EvidenceKind.STATIC if location else EvidenceKind.HEURISTIC,
                    "legacy.python.edge",
                    "Relationship translated from the V2 graph",
                    location,
                    confidence,
                )
            ]
        attributes = dict(raw.get("attributes") or {})
        attributes.setdefault("legacy", {})["edge_type"] = legacy_type
        edges.append(
            SemanticEdge(
                id=str(raw.get("id") or _edge_id(source, target, legacy_type, index)),
                source=source,
                target=target,
                kind=LEGACY_EDGE_MAP.get(legacy_type, EdgeKind.RELATED_TO),
                confidence=confidence,
                evidence=evidence,
                attributes=attributes,
            )
        )

    graph = SemanticGraph(
        nodes=nodes,
        edges=edges,
        metadata={
            "language": "python",
            "framework": framework,
            "source_graph_schema": legacy_graph.get("schema") or "feynmap.v2.legacy",
            "source_graph_version": legacy_graph.get("schema_version"),
            "adapter": "python-v2-bridge",
        },
    )
    graph.validate()
    return graph


def _node_location(raw: Dict[str, Any]) -> Optional[SourceLocation]:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    path = source.get("path") or source.get("file") or raw.get("file") or metadata.get("file_path")
    if not path:
        return None
    return SourceLocation(str(path), _int_or_none(source.get("line") or raw.get("line") or metadata.get("line_number")), _int_or_none(source.get("end_line") or raw.get("end_line")))


def _edge_location(raw: Dict[str, Any]) -> Optional[SourceLocation]:
    evidence = raw.get("evidence")
    if isinstance(evidence, dict):
        path = evidence.get("file") or evidence.get("path")
        if path:
            return SourceLocation(str(path), _int_or_none(evidence.get("line")))
    path = raw.get("file")
    if path:
        return SourceLocation(str(path), _int_or_none(raw.get("line")))
    return None


def _evidence_list(raw: Any, fallback: Optional[SourceLocation], detector: str) -> List[Evidence]:
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    result: List[Evidence] = []
    for item in items:
        if isinstance(item, str):
            result.append(Evidence(EvidenceKind.STATIC, detector, item, fallback, 0.95))
        elif isinstance(item, dict):
            path = item.get("file") or item.get("path")
            location = SourceLocation(str(path), _int_or_none(item.get("line"))) if path else fallback
            result.append(Evidence(EvidenceKind.STATIC, str(item.get("detector") or detector), str(item.get("detail") or item.get("reason") or ""), location, max(0.0, min(1.0, float(item.get("confidence", 0.95))))))
    return result


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _edge_id(source: str, target: str, edge_type: str, index: int) -> str:
    digest = hashlib.sha1(("%s|%s|%s|%s" % (source, target, edge_type, index)).encode("utf-8")).hexdigest()[:12]
    return "edge:%s" % digest
