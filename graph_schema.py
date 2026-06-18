"""Stable, versioned graph schema for FeynMap.

The v1 contract is deliberately additive: existing consumers can keep reading the
``nodes`` and ``edges`` arrays while newer consumers gain normalized fields,
validation diagnostics, and migration support.
"""

import hashlib
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple, Type


GRAPH_SCHEMA_NAME = "feynmap.graph"
GRAPH_SCHEMA_VERSION = "1.0.0"
GRAPH_SCHEMA_MAJOR = 1
GENERATOR_NAME = "FeynMap"
GENERATOR_VERSION = "2.0.0"

NODE_TYPES = {
    "VERTEX",
    "PARTICLE",
    "TRANSFORM",
    "MEDIATOR",
    "FRONTEND",
    "JAVASCRIPT",
    "AJAX",
    "DEPENDENCY",
    "UNKNOWN",
}

EDGE_TYPES = {
    "CALL",
    "CONTAINS",
    "PARTICLE_ENTANGLEMENT",
    "SERIALIZER_ENTANGLEMENT",
    "AJAX",
    "EVENT",
    "OBSERVATION",
    "VIRTUAL",
    "DEPENDENCY",
}

NODE_CORE_FIELDS = {
    "id",
    "name",
    "qualified_name",
    "type",
    "language",
    "file",
    "source",
    "metadata",
    "attributes",
}
EDGE_CORE_FIELDS = {
    "id",
    "source",
    "target",
    "type",
    "confidence",
    "evidence",
    "attributes",
    "resolution",
    "line",
}


class GraphSchemaError(ValueError):
    """Raised when strict schema validation fails."""


def normalize_graph(
    graph_data: Dict[str, Any],
    *,
    strict: bool = False,
    generator_version: str = GENERATOR_VERSION,
) -> Dict[str, Any]:
    """Normalize a legacy or v1 graph into the canonical v1 representation."""
    graph = deepcopy(graph_data or {})
    incoming_version = str(graph.get("schema_version") or "0.0.0")
    graph = migrate_graph(graph, incoming_version, GRAPH_SCHEMA_VERSION)

    normalized_nodes = [_normalize_node(node) for node in graph.get("nodes", [])]
    normalized_edges = [_normalize_edge(edge) for edge in graph.get("edges", [])]

    diagnostics = validate_graph(
        {"nodes": normalized_nodes, "edges": normalized_edges}, strict=False
    )
    normalized = {
        "schema": GRAPH_SCHEMA_NAME,
        "schema_version": GRAPH_SCHEMA_VERSION,
        "generator": {
            "name": GENERATOR_NAME,
            "version": generator_version,
        },
        "graph": {
            "directed": True,
            "multigraph": True,
            "node_count": len(normalized_nodes),
            "edge_count": len(normalized_edges),
        },
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "diagnostics": diagnostics,
        "extensions": _mapping(graph.get("extensions")),
    }

    top_level_extensions = {
        key: value
        for key, value in graph.items()
        if key
        not in {
            "schema",
            "schema_version",
            "generator",
            "graph",
            "nodes",
            "edges",
            "diagnostics",
            "extensions",
        }
    }
    if top_level_extensions:
        normalized["extensions"].update(top_level_extensions)

    if strict and diagnostics["errors"]:
        raise GraphSchemaError("; ".join(diagnostics["errors"]))
    return normalized


def validate_graph(graph_data: Dict[str, Any], *, strict: bool = False) -> Dict[str, Any]:
    """Validate graph identity, references, field types, and schema invariants."""
    errors: List[str] = []
    warnings: List[str] = []
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        nodes = []
    if not isinstance(edges, list):
        errors.append("edges must be a list")
        edges = []

    node_ids: List[str] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"nodes[{index}].id must be a non-empty string")
            continue
        node_ids.append(node_id)
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            warnings.append(
                f"node {node_id!r} uses unregistered type {node_type!r}; preserved as an extension"
            )
        source = node.get("source", {})
        if source and not isinstance(source, dict):
            errors.append(f"node {node_id!r}.source must be an object")

    duplicate_nodes = _duplicates(node_ids)
    for node_id in duplicate_nodes:
        errors.append(f"duplicate node id: {node_id}")

    known_nodes = set(node_ids)
    edge_ids: List[str] = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edges[{index}] must be an object")
            continue
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            errors.append(f"edges[{index}].id must be a non-empty string")
        else:
            edge_ids.append(edge_id)
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, str) or not source:
            errors.append(f"edges[{index}].source must be a non-empty string")
        elif source not in known_nodes:
            warnings.append(f"edge {edge_id or index!r} references missing source {source!r}")
        if not isinstance(target, str) or not target:
            errors.append(f"edges[{index}].target must be a non-empty string")
        elif target not in known_nodes:
            warnings.append(f"edge {edge_id or index!r} references missing target {target!r}")
        edge_type = edge.get("type")
        if edge_type not in EDGE_TYPES:
            warnings.append(
                f"edge {edge_id or index!r} uses unregistered type {edge_type!r}; preserved as an extension"
            )
        confidence = edge.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0
        ):
            errors.append(f"edge {edge_id or index!r}.confidence must be null or between 0 and 1")

    duplicate_edges = _duplicates(edge_ids)
    for edge_id in duplicate_edges:
        errors.append(f"duplicate edge id: {edge_id}")

    diagnostics = {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }
    if strict and errors:
        raise GraphSchemaError("; ".join(errors))
    return diagnostics


def migrate_graph(
    graph_data: Dict[str, Any], from_version: str, to_version: str
) -> Dict[str, Any]:
    """Migrate a graph between supported schema versions.

    v0 represents FeynMap's historical unversioned ``nodes``/``edges`` shape.
    Migrations are intentionally explicit so future major versions can be added
    without silently mutating old artifacts.
    """
    source_major = _major(from_version)
    target_major = _major(to_version)
    if target_major != GRAPH_SCHEMA_MAJOR:
        raise GraphSchemaError(
            f"unsupported target graph schema {to_version}; this runtime supports major {GRAPH_SCHEMA_MAJOR}"
        )
    if source_major > GRAPH_SCHEMA_MAJOR:
        raise GraphSchemaError(
            f"graph schema {from_version} is newer than supported {GRAPH_SCHEMA_VERSION}"
        )
    return deepcopy(graph_data or {})


def schema_compatibility(version: str) -> Dict[str, Any]:
    """Describe whether a schema version can be read by this runtime."""
    major = _major(version)
    compatible = major in {0, GRAPH_SCHEMA_MAJOR}
    return {
        "requested_version": version,
        "supported_version": GRAPH_SCHEMA_VERSION,
        "compatible": compatible,
        "requires_migration": major == 0,
    }


def install_stable_graph_schema(extractor_class: Type[Any]) -> None:
    """Ensure every direct ``FeynExtractor.scan`` result uses the stable schema."""
    if getattr(extractor_class, "_stable_graph_schema_installed", False):
        return
    original_scan = extractor_class.scan

    def scan(self: Any) -> Dict[str, Any]:
        graph = original_scan(self)
        normalized = normalize_graph(graph)
        self.graph = normalized
        return normalized

    extractor_class.scan = scan
    extractor_class._stable_graph_schema_installed = True


def _normalize_node(node: Any) -> Dict[str, Any]:
    source = node if isinstance(node, dict) else {}
    node_id = str(source.get("id") or "")
    name = str(source.get("name") or node_id.rsplit(".", 1)[-1] or node_id)
    metadata = _mapping(source.get("metadata"))
    line_start = source.get("line_start", metadata.get("line_start"))
    line_end = source.get("line_end", metadata.get("line_end"))
    source_location = _mapping(source.get("source"))
    source_location.setdefault("file", source.get("file") or metadata.get("file"))
    source_location.setdefault("line_start", line_start)
    source_location.setdefault("line_end", line_end)

    attributes = _mapping(source.get("attributes"))
    for key, value in source.items():
        if key not in NODE_CORE_FIELDS and key not in {"line_start", "line_end"}:
            attributes.setdefault(key, value)

    metadata.setdefault("line_start", line_start)
    metadata.setdefault("line_end", line_end)
    metadata.setdefault("file", source_location.get("file"))

    return {
        "id": node_id,
        "name": name,
        "qualified_name": str(source.get("qualified_name") or name),
        "type": str(source.get("type") or "UNKNOWN"),
        "language": source.get("language"),
        "file": source_location.get("file"),
        "source": source_location,
        "metadata": metadata,
        "attributes": attributes,
        "line_start": line_start,
        "line_end": line_end,
    }


def _normalize_edge(edge: Any) -> Dict[str, Any]:
    source = edge if isinstance(edge, dict) else {}
    edge_source = str(source.get("source") or "")
    edge_target = str(source.get("target") or "")
    edge_type = str(source.get("type") or "DEPENDENCY")
    confidence = source.get("confidence")
    if isinstance(confidence, (int, float)):
        confidence = round(max(0.0, min(1.0, float(confidence))), 4)
    else:
        confidence = None

    attributes = _mapping(source.get("attributes"))
    for key, value in source.items():
        if key not in EDGE_CORE_FIELDS:
            attributes.setdefault(key, value)

    evidence = source.get("evidence")
    if evidence is None:
        evidence_list: List[str] = []
    elif isinstance(evidence, list):
        evidence_list = [str(item) for item in evidence]
    else:
        evidence_list = [str(evidence)]

    edge_id = str(source.get("id") or _edge_id(edge_source, edge_target, edge_type))
    return {
        "id": edge_id,
        "source": edge_source,
        "target": edge_target,
        "type": edge_type,
        "confidence": confidence,
        "evidence": evidence_list,
        "attributes": attributes,
        "resolution": source.get("resolution"),
        "line": source.get("line"),
    }


def _edge_id(source: str, target: str, edge_type: str) -> str:
    payload = f"{source}\x1f{edge_type}\x1f{target}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"edge:{digest}"


def _major(version: str) -> int:
    try:
        return int(str(version).split(".", 1)[0])
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _duplicates(values: Iterable[str]) -> List[str]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


__all__ = [
    "GRAPH_SCHEMA_NAME",
    "GRAPH_SCHEMA_VERSION",
    "GraphSchemaError",
    "normalize_graph",
    "validate_graph",
    "migrate_graph",
    "schema_compatibility",
    "install_stable_graph_schema",
]
