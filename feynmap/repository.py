"""Repository-level orchestration helpers for merging language graphs."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode


REPOSITORY_NODE_ID = "repository:root"
REPOSITORY_QUALIFIED_NAME = "repository"
REPOSITORY_ROOT = "."


def merge_language_graphs(
    root: Path,
    analyzed: Sequence[Tuple[str, float, SemanticGraph]],
) -> SemanticGraph:
    """Merge independently analyzed language graphs into one repository graph.

    The semantic repository root is intentionally clone-independent. Local
    checkout paths belong to repository snapshot metadata (`root_hint`), not to
    the canonical graph. This keeps graph identity stable when the same source
    tree is analyzed from different filesystem locations.
    """
    repository_id = REPOSITORY_NODE_ID
    repository_node = SemanticNode(
        id=repository_id,
        name=REPOSITORY_QUALIFIED_NAME,
        qualified_name=REPOSITORY_QUALIFIED_NAME,
        kind=NodeKind.REPOSITORY,
        attributes={"repository": {"root": REPOSITORY_ROOT}},
        evidence=[Evidence(EvidenceKind.STATIC, "repository.orchestrator", "Canonical repository analysis root", None, 1.0)],
    )
    merged = SemanticGraph(
        nodes=[repository_node],
        metadata={"project_root": REPOSITORY_ROOT, "adapter": "repository-orchestrator"},
    )
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
