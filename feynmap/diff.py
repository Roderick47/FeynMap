"""Semantic and repository-content diffs between immutable FeynMap snapshots.

Diffs operate on stored snapshots rather than source files. They distinguish the
repository content delta from the semantic graph delta so incremental analysis,
MCP clients, and coding agents can reason about what changed without reparsing
historical states.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List

from .core import SemanticEdge, SemanticGraph, SemanticNode
from .snapshots import RepositorySnapshot, SnapshotStore


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def diff_file_inventories(before: RepositorySnapshot, after: RepositorySnapshot) -> Dict[str, Any]:
    """Return added, removed, modified, and unchanged repository paths."""
    left = {item.path: item for item in before.files}
    right = {item.path: item for item in after.files}
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    common = sorted(set(left) & set(right))
    modified = [path for path in common if left[path].sha256 != right[path].sha256]
    unchanged = [path for path in common if left[path].sha256 == right[path].sha256]
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged_count": len(unchanged),
        "changed_count": len(added) + len(removed) + len(modified),
    }


def _node_payload(node: SemanticNode) -> Dict[str, Any]:
    return node.to_dict()


def _edge_key(edge: SemanticEdge) -> str:
    return "%s|%s|%s" % (edge.source, edge.kind.value, edge.target)


def _edge_payload(edge: SemanticEdge) -> Dict[str, Any]:
    payload = edge.to_dict()
    payload.pop("id", None)
    return payload


def _edge_groups(graph: SemanticGraph) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for edge in graph.edges:
        groups[_edge_key(edge)].append(_edge_payload(edge))
    for key in groups:
        groups[key] = sorted(groups[key], key=_canonical)
    return dict(groups)


def diff_graphs(before: SemanticGraph, after: SemanticGraph) -> Dict[str, Any]:
    """Compare two semantic graphs using stable node IDs and relationship keys.

    Relationship identity is `(source, kind, target)` rather than the generated
    edge ID, because edge IDs may include detector/location details that can
    change while the underlying semantic relationship remains the same.
    """
    left_nodes = {node.id: node for node in before.nodes}
    right_nodes = {node.id: node for node in after.nodes}

    added_node_ids = sorted(set(right_nodes) - set(left_nodes))
    removed_node_ids = sorted(set(left_nodes) - set(right_nodes))
    common_node_ids = sorted(set(left_nodes) & set(right_nodes))
    changed_node_ids = [
        node_id
        for node_id in common_node_ids
        if _canonical(_node_payload(left_nodes[node_id])) != _canonical(_node_payload(right_nodes[node_id]))
    ]

    left_edges = _edge_groups(before)
    right_edges = _edge_groups(after)
    added_edge_keys = sorted(set(right_edges) - set(left_edges))
    removed_edge_keys = sorted(set(left_edges) - set(right_edges))
    common_edge_keys = sorted(set(left_edges) & set(right_edges))
    changed_edge_keys = [
        key
        for key in common_edge_keys
        if _canonical(left_edges[key]) != _canonical(right_edges[key])
    ]

    return {
        "nodes": {
            "added": [right_nodes[node_id].to_dict() for node_id in added_node_ids],
            "removed": [left_nodes[node_id].to_dict() for node_id in removed_node_ids],
            "changed": [
                {
                    "id": node_id,
                    "before": left_nodes[node_id].to_dict(),
                    "after": right_nodes[node_id].to_dict(),
                }
                for node_id in changed_node_ids
            ],
            "added_count": len(added_node_ids),
            "removed_count": len(removed_node_ids),
            "changed_count": len(changed_node_ids),
        },
        "relationships": {
            "added": [{"key": key, "edges": right_edges[key]} for key in added_edge_keys],
            "removed": [{"key": key, "edges": left_edges[key]} for key in removed_edge_keys],
            "changed": [
                {"key": key, "before": left_edges[key], "after": right_edges[key]}
                for key in changed_edge_keys
            ],
            "added_count": len(added_edge_keys),
            "removed_count": len(removed_edge_keys),
            "changed_count": len(changed_edge_keys),
        },
    }


def diff_snapshots(
    before_snapshot: RepositorySnapshot,
    before_graph: SemanticGraph,
    after_snapshot: RepositorySnapshot,
    after_graph: SemanticGraph,
) -> Dict[str, Any]:
    """Return a repository + semantic delta for two snapshots of one repository."""
    if before_snapshot.repository_key != after_snapshot.repository_key:
        raise ValueError("cannot diff snapshots from different repositories")
    return {
        "repository_key": before_snapshot.repository_key,
        "before_snapshot_id": before_snapshot.snapshot_id,
        "after_snapshot_id": after_snapshot.snapshot_id,
        "before_revision": before_snapshot.revision,
        "after_revision": after_snapshot.revision,
        "content_changed": before_snapshot.content_hash != after_snapshot.content_hash,
        "graph_changed": before_snapshot.graph_hash != after_snapshot.graph_hash,
        "files": diff_file_inventories(before_snapshot, after_snapshot),
        "semantic": diff_graphs(before_graph, after_graph),
    }


def diff_store_snapshots(store: SnapshotStore, before_snapshot_id: str, after_snapshot_id: str) -> Dict[str, Any]:
    before_snapshot, before_graph = store.load(before_snapshot_id)
    after_snapshot, after_graph = store.load(after_snapshot_id)
    return diff_snapshots(before_snapshot, before_graph, after_snapshot, after_graph)
