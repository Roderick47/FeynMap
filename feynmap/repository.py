"""Repository-level orchestration helpers for merging language graphs."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode


def merge_language_graphs(
    root: Path,
    analyzed: Sequence[Tuple[str, float, SemanticGraph]],
) -> SemanticGraph:
    """Merge independently analyzed language graphs into one repository graph."""
    repository_id = "repository:%s" % hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:14]
    repository_node = SemanticNode(
        id=repository_id,
        name=root.name,
        qualified_name=str(root),
        kind=NodeKind.REPOSITORY,
        attributes={"repository": {"root": str(root)}},
        evidence=[Evidence(EvidenceKind.STATIC, "repository.orchestrator", "Repository analysis root", None, 1.0)],
    )
    merged = SemanticGraph(nodes=[repository_node], metadata={"project_root": str(root), "adapter": "repository-orchestrator"})
    language_metadata: List[Dict[str, object]] = []
    frameworks: List[str] = []

    for language, score, graph in analyzed:
        existing_ids = {node.id for node in merged.nodes}
        for node in graph.nodes:
            if node.id not in existing_ids:
                merged.add_node(node)
                existing_ids.add(node.id)
        existing_edge_ids = {edge.id for edge in merged.edges}
        for edge in graph.edges:
            if edge.id not in existing_edge_ids:
                merged.add_edge(edge)
                existing_edge_ids.add(edge.id)

        applied = graph.metadata.get("frameworks_applied", [])
        if isinstance(applied, list):
            for name in applied:
                if str(name) not in frameworks:
                    frameworks.append(str(name))
        language_metadata.append(
            {
                "name": language,
                "detection_score": round(float(score), 4),
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "frameworks": list(applied) if isinstance(applied, list) else [],
            }
        )

    incoming_contains = {edge.target for edge in merged.edges if edge.kind == EdgeKind.CONTAINS}
    roots = [node for node in merged.nodes if node.id != repository_id and node.id not in incoming_contains]
    edge_keys = {(edge.source, edge.target, edge.kind.value) for edge in merged.edges}
    for node in roots:
        key = (repository_id, node.id, EdgeKind.CONTAINS.value)
        if key in edge_keys:
            continue
        raw = "%s|%s" % (repository_id, node.id)
        evidence = Evidence(EvidenceKind.STATIC, "repository.orchestrator", "Repository contains language root", node.location, 1.0)
        merged.add_edge(
            SemanticEdge(
                "edge:repository:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
                repository_id,
                node.id,
                EdgeKind.CONTAINS,
                1.0,
                [evidence],
            )
        )
        edge_keys.add(key)

    merged.metadata.update(
        {
            "languages": language_metadata,
            "language_names": [str(item["name"]) for item in language_metadata],
            "language_count": len(language_metadata),
            "frameworks_applied": frameworks,
            "framework": frameworks[0] if len(frameworks) == 1 else None,
        }
    )
    merged.validate()
    return merged
