"""Token-budgeted grounding context over immutable FeynMap snapshots.

This module is deliberately transport-neutral. MCP, HTTP, a Rust implementation,
or local CLI tooling can all consume the same dictionary payloads without
reparsing repository source code.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .core import SemanticEdge, SemanticGraph, SemanticNode
from .query import FeynMapQuery
from .snapshots import RepositorySnapshot, SnapshotStore

MIN_CONTEXT_TOKENS = 512


def estimate_tokens(payload: Any) -> int:
    """Deterministic tokenizer-independent estimate suitable for budget guards.

    The reference implementation uses a conservative four UTF-8 characters per
    token approximation. The budget contract is intentionally separate from any
    vendor tokenizer so a future Rust implementation can remain compatible.
    """
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return max(1, int(math.ceil(len(text) / 4.0)))


def _compact_evidence(items: Sequence[Dict[str, Any]], limit: int = 2) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in list(items)[: max(0, limit)]:
        keep = {
            key: item[key]
            for key in ("kind", "detector", "detail", "location", "confidence")
            if key in item
        }
        compact.append(keep)
    return compact


def _compact_node(node: SemanticNode) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "kind": node.kind.value,
        "confidence": round(node.confidence, 4),
        "confidence_tier": node.confidence_tier.value,
    }
    if node.qualified_name:
        payload["qualified_name"] = node.qualified_name
    if node.language:
        payload["language"] = node.language
    if node.framework:
        payload["framework"] = node.framework
    if node.location:
        payload["location"] = node.location.to_dict()
    evidence = [item.to_dict() for item in node.evidence]
    if evidence:
        payload["evidence"] = _compact_evidence(evidence)
    return payload


def _compact_edge(edge: SemanticEdge) -> Dict[str, Any]:
    payload = {
        "source": edge.source,
        "relationship": edge.kind.value,
        "target": edge.target,
        "confidence": round(float(edge.confidence), 4),
        "confidence_tier": edge.confidence_tier.value,
    }
    evidence = [item.to_dict() for item in edge.evidence]
    if evidence:
        payload["evidence"] = _compact_evidence(evidence)
    return payload


@dataclass(frozen=True)
class ContextBudget:
    max_tokens: int = 4000
    max_nodes: int = 80
    max_edges: int = 120

    def normalized(self) -> "ContextBudget":
        """Return effective bounds, enforcing the minimum evidence-bearing payload size."""
        return ContextBudget(
            max_tokens=max(MIN_CONTEXT_TOKENS, int(self.max_tokens)),
            max_nodes=max(1, int(self.max_nodes)),
            max_edges=max(1, int(self.max_edges)),
        )


class StoredSnapshotContext:
    """Query one stored semantic snapshot without touching repository source."""

    def __init__(self, snapshot: RepositorySnapshot, graph: SemanticGraph) -> None:
        self.snapshot = snapshot
        self.graph = graph
        self.query = FeynMapQuery(graph)

    @classmethod
    def load(cls, store: SnapshotStore, snapshot_id: str) -> "StoredSnapshotContext":
        snapshot, graph = store.load(snapshot_id)
        return cls(snapshot, graph)

    @classmethod
    def load_current(cls, store: SnapshotStore, repository_key: str) -> "StoredSnapshotContext":
        loaded = store.load_current(repository_key)
        if loaded is None:
            raise KeyError("repository has no current snapshot: %s" % repository_key)
        return cls(loaded[0], loaded[1])

    def repository_summary(self) -> Dict[str, Any]:
        by_kind: Dict[str, int] = {}
        by_language: Dict[str, int] = {}
        for node in self.graph.nodes:
            by_kind[node.kind.value] = by_kind.get(node.kind.value, 0) + 1
            if node.language:
                by_language[node.language] = by_language.get(node.language, 0) + 1
        integration = self.graph.metadata.get("integration") or {}
        return {
            "snapshot": self.snapshot.to_dict(include_files=False),
            "graph": {
                "node_count": len(self.graph.nodes),
                "edge_count": len(self.graph.edges),
                "evidence_coverage": round(self.graph.evidence_coverage(), 4),
                "nodes_by_kind": dict(sorted(by_kind.items())),
                "nodes_by_language": dict(sorted(by_language.items())),
                "languages": self.graph.metadata.get("language_names", []),
                "frameworks": self.graph.metadata.get("frameworks_applied", []),
                "integration": integration,
                "diagnostics": self.graph.diagnostics,
                "analysis_contract_version": self.graph.metadata.get("analysis_contract_version"),
            },
            "grounding": {
                "known": "Facts included below are backed by the stored semantic graph and its evidence.",
                "unknown": "A missing relationship means FeynMap has no current evidence for it; absence is not proof of impossibility.",
            },
        }

    def symbol(self, value: str) -> Dict[str, Any]:
        node = self.query.resolve(value)
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "symbol": node.to_dict(),
            "outgoing": [edge.to_dict() for edge in self.graph.outgoing(node.id)],
            "incoming": [edge.to_dict() for edge in self.graph.incoming(node.id)],
        }

    def validate_claim(self, source: str, target: str, relationship: Optional[str] = None) -> Dict[str, Any]:
        payload = self.query.validate_claim(source, target, relationship)
        payload["snapshot_id"] = self.snapshot.snapshot_id
        return payload

    def context_bundle(
        self,
        symbol: str,
        depth: int = 2,
        budget: Optional[ContextBudget] = None,
    ) -> Dict[str, Any]:
        requested = budget or ContextBudget()
        budget = requested.normalized()
        root = self.query.resolve(symbol)
        candidates = self._ranked_neighborhood(root.id, max(0, int(depth)))

        payload: Dict[str, Any] = {
            "snapshot": {
                "snapshot_id": self.snapshot.snapshot_id,
                "repository_key": self.snapshot.repository_key,
                "revision": self.snapshot.revision,
                "content_hash": self.snapshot.content_hash,
                "graph_hash": self.snapshot.graph_hash,
            },
            "root": _compact_node(root),
            "nodes": [],
            "relationships": [],
            "grounding": {
                "known": "Included relationships are stored graph facts with provenance where available.",
                "unknown": "Omitted or absent relationships must be treated as unknown, not false.",
                "budgeting": "Context is deterministically truncated to the effective approximate-token budget.",
            },
        }

        included_nodes = {root.id}
        for _, node in candidates["nodes"]:
            if len(payload["nodes"]) >= budget.max_nodes:
                break
            compact = _compact_node(node)
            trial = dict(payload)
            trial["nodes"] = list(payload["nodes"]) + [compact]
            if estimate_tokens(trial) > budget.max_tokens:
                break
            payload["nodes"].append(compact)
            included_nodes.add(node.id)

        for _, edge in candidates["edges"]:
            if len(payload["relationships"]) >= budget.max_edges:
                break
            if edge.source not in included_nodes or edge.target not in included_nodes:
                continue
            compact = _compact_edge(edge)
            trial = dict(payload)
            trial["relationships"] = list(payload["relationships"]) + [compact]
            if estimate_tokens(trial) > budget.max_tokens:
                break
            payload["relationships"].append(compact)

        budget_payload = {
            "requested_max_tokens": int(requested.max_tokens),
            "max_tokens": budget.max_tokens,
            "minimum_supported_tokens": MIN_CONTEXT_TOKENS,
            "max_nodes": budget.max_nodes,
            "max_edges": budget.max_edges,
            "included_nodes": 1 + len(payload["nodes"]),
            "included_relationships": len(payload["relationships"]),
            "truncated": (
                len(payload["nodes"]) < len(candidates["nodes"])
                or len(payload["relationships"]) < len(candidates["edges"])
            ),
        }
        payload["budget"] = budget_payload

        # Budget metadata itself has a cost. Trim lower-priority material until
        # the final serialized payload fits the effective budget.
        while estimate_tokens(payload) > budget.max_tokens and payload["relationships"]:
            payload["relationships"].pop()
            payload["budget"]["included_relationships"] = len(payload["relationships"])
            payload["budget"]["truncated"] = True
        while estimate_tokens(payload) > budget.max_tokens and payload["nodes"]:
            payload["nodes"].pop()
            payload["budget"]["included_nodes"] = 1 + len(payload["nodes"])
            payload["budget"]["truncated"] = True

        estimated = estimate_tokens(payload)
        payload["budget"]["estimated_tokens"] = estimated
        return payload

    def unresolved(self, limit: int = 100) -> Dict[str, Any]:
        python_calls: List[Dict[str, Any]] = []
        for node in self.graph.nodes:
            python = node.attributes.get("python")
            if not isinstance(python, dict):
                continue
            unresolved = python.get("unresolved_calls")
            if not isinstance(unresolved, list) or not unresolved:
                continue
            python_calls.append({
                "node": node.id,
                "qualified_name": node.qualified_name,
                "calls": list(unresolved),
            })
            if len(python_calls) >= max(1, int(limit)):
                break
        integration = self.graph.metadata.get("integration") or {}
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "python_unresolved_calls": python_calls,
            "integration_unresolved_contracts": integration.get("unresolved_contracts", 0) if isinstance(integration, dict) else 0,
            "integration_unresolved_sample": integration.get("unresolved_sample", []) if isinstance(integration, dict) else [],
        }

    def _ranked_neighborhood(self, root_id: str, depth: int) -> Dict[str, List[Tuple[int, Any]]]:
        node_distance: Dict[str, int] = {root_id: 0}
        edge_distance: Dict[str, int] = {}
        frontier = [root_id]
        for current_depth in range(depth):
            next_frontier: List[str] = []
            for node_id in frontier:
                edges = list(self.graph.outgoing(node_id)) + list(self.graph.incoming(node_id))
                for edge in edges:
                    edge_distance.setdefault(edge.id, current_depth)
                    neighbor = edge.target if edge.source == node_id else edge.source
                    if neighbor in node_distance:
                        continue
                    node_distance[neighbor] = current_depth + 1
                    next_frontier.append(neighbor)
            frontier = next_frontier
            if not frontier:
                break

        nodes: List[Tuple[int, SemanticNode]] = []
        for node_id, distance in node_distance.items():
            if node_id == root_id:
                continue
            node = self.graph.node(node_id)
            if node is not None:
                nodes.append((distance, node))
        nodes.sort(key=lambda item: (item[0], -item[1].confidence, item[1].id))

        edges: List[Tuple[int, SemanticEdge]] = []
        for edge in self.graph.edges:
            if edge.id in edge_distance:
                edges.append((edge_distance[edge.id], edge))
        edges.sort(key=lambda item: (item[0], -float(item[1].confidence), item[1].kind.value, item[1].source, item[1].target))
        return {"nodes": nodes, "edges": edges}
