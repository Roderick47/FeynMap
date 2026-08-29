"""Transport-neutral grounding service for the future MCP/API boundary.

This module deliberately does not depend on an MCP SDK. It defines stable tool
contracts and dispatches them against immutable stored semantic snapshots. The
actual MCP transport can therefore remain a thin adapter over the same service,
and a future Rust implementation can reproduce the same JSON-compatible
contracts without inheriting Python-specific server internals.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .context import ContextBudget, StoredSnapshotContext
from .core import EdgeKind, SemanticEdge
from .diff import diff_store_snapshots
from .snapshots import SnapshotStore


GROUNDING_TOOL_CONTRACT_VERSION = "1.0.0"
JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


@dataclass(frozen=True)
class GroundingTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    read_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "read_only": self.read_only,
            "contract_version": GROUNDING_TOOL_CONTRACT_VERSION,
        }


def _object_schema(
    properties: Optional[Dict[str, Any]] = None,
    required: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "type": "object",
        "properties": dict(properties or {}),
        "required": list(required or []),
        "additionalProperties": False,
    }


_DEPTH = {"type": "integer", "minimum": 0, "maximum": 12, "default": 2}
_SYMBOL = {"type": "string", "minLength": 1}
_SNAPSHOT = {"type": "string", "minLength": 1}


GROUNDING_TOOLS: Tuple[GroundingTool, ...] = (
    GroundingTool(
        "repository_summary",
        "Return identity, languages, frameworks, diagnostics, evidence coverage, and graph size for the selected immutable snapshot.",
        _object_schema(),
    ),
    GroundingTool(
        "get_symbol",
        "Return one grounded semantic symbol and its direct incoming/outgoing relationships with evidence.",
        _object_schema({"symbol": _SYMBOL}, ["symbol"]),
    ),
    GroundingTool(
        "find_callers",
        "Walk callers/incoming semantic relationships from a symbol in the stored graph.",
        _object_schema({"symbol": _SYMBOL, "depth": _DEPTH}, ["symbol"]),
    ),
    GroundingTool(
        "find_dependencies",
        "Walk dependencies/outgoing semantic relationships from a symbol in the stored graph.",
        _object_schema({"symbol": _SYMBOL, "depth": _DEPTH}, ["symbol"]),
    ),
    GroundingTool(
        "change_impact",
        "Return the stored caller/impact closure for a symbol. This reports evidenced impact, not hypothetical unseen relationships.",
        _object_schema({"symbol": _SYMBOL, "depth": {"type": "integer", "minimum": 0, "maximum": 20, "default": 4}}, ["symbol"]),
    ),
    GroundingTool(
        "validate_claim",
        "Check whether the selected snapshot contains evidence for a claimed source-to-target relationship.",
        _object_schema(
            {"source": _SYMBOL, "target": _SYMBOL, "relationship": {"type": "string", "minLength": 1}},
            ["source", "target"],
        ),
    ),
    GroundingTool(
        "trace_path",
        "Find one evidenced graph path between two symbols, bounded by depth. No path means unknown/no current evidence, not impossible.",
        _object_schema(
            {
                "source": _SYMBOL,
                "target": _SYMBOL,
                "max_depth": {"type": "integer", "minimum": 0, "maximum": 20, "default": 6},
                "direction": {"type": "string", "enum": ["outgoing", "incoming", "both"], "default": "outgoing"},
            },
            ["source", "target"],
        ),
    ),
    GroundingTool(
        "find_integrations",
        "Return integration/boundary relationships from the selected stored graph, optionally scoped to a symbol.",
        _object_schema(
            {
                "symbol": _SYMBOL,
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            }
        ),
    ),
    GroundingTool(
        "explain_evidence",
        "Explain the evidence attached to a symbol and its direct relationships.",
        _object_schema({"symbol": _SYMBOL}, ["symbol"]),
    ),
    GroundingTool(
        "unresolved",
        "Return unresolved Python calls and integration contracts so clients can preserve uncertainty instead of hallucinating an answer.",
        _object_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}}),
    ),
    GroundingTool(
        "context_bundle",
        "Return a deterministic evidence-preserving neighborhood around a symbol under an approximate token budget.",
        _object_schema(
            {
                "symbol": _SYMBOL,
                "depth": _DEPTH,
                "max_tokens": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 4000},
                "max_nodes": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 80},
                "max_edges": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 120},
            },
            ["symbol"],
        ),
    ),
    GroundingTool(
        "semantic_diff",
        "Compare two immutable snapshots of the same repository and return file plus semantic graph changes without reparsing source.",
        _object_schema({"before_snapshot": _SNAPSHOT, "after_snapshot": _SNAPSHOT}, ["before_snapshot", "after_snapshot"]),
    ),
)

_TOOL_BY_NAME = {tool.name: tool for tool in GROUNDING_TOOLS}
_INTEGRATION_KINDS = {
    EdgeKind.REQUESTS,
    EdgeKind.FLOWS_TO,
    EdgeKind.LOADS,
    EdgeKind.RENDERS,
    EdgeKind.INVOKES,
    EdgeKind.SPAWNS,
    EdgeKind.CONNECTS_TO,
    EdgeKind.ROUTES_TO,
    EdgeKind.EMITS,
    EdgeKind.SUBSCRIBES,
}


class GroundingService:
    """Read-only application service that future MCP/HTTP transports can expose."""

    def __init__(self, store: SnapshotStore, snapshot_id: str) -> None:
        self.store = store
        self.context = StoredSnapshotContext.load(store, snapshot_id)
        self.snapshot = self.context.snapshot
        self.graph = self.context.graph
        self.query = self.context.query

    @classmethod
    def from_current(cls, store: SnapshotStore, repository_key: str) -> "GroundingService":
        snapshot_id = store.current_snapshot_id(repository_key)
        if not snapshot_id:
            raise KeyError("repository has no current snapshot: %s" % repository_key)
        return cls(store, snapshot_id)

    @staticmethod
    def tool_catalog() -> List[Dict[str, Any]]:
        return [tool.to_dict() for tool in GROUNDING_TOOLS]

    @staticmethod
    def tool(name: str) -> GroundingTool:
        try:
            return _TOOL_BY_NAME[name]
        except KeyError:
            raise KeyError("unknown grounding tool: %s" % name)

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Dispatch one versioned grounding tool using JSON-compatible arguments."""
        self.tool(name)
        args = dict(arguments or {})
        if name == "repository_summary":
            return self.context.repository_summary()
        if name == "get_symbol":
            return self.context.symbol(self._required(args, "symbol"))
        if name == "find_callers":
            return self._with_snapshot(self.query.callers(self._required(args, "symbol"), depth=int(args.get("depth", 2))))
        if name == "find_dependencies":
            return self._with_snapshot(self.query.dependencies(self._required(args, "symbol"), depth=int(args.get("depth", 2))))
        if name == "change_impact":
            return self._with_snapshot(self.query.impact(self._required(args, "symbol"), depth=int(args.get("depth", 4))))
        if name == "validate_claim":
            return self.context.validate_claim(
                self._required(args, "source"),
                self._required(args, "target"),
                args.get("relationship"),
            )
        if name == "trace_path":
            return self.trace_path(
                self._required(args, "source"),
                self._required(args, "target"),
                max_depth=int(args.get("max_depth", 6)),
                direction=str(args.get("direction", "outgoing")),
            )
        if name == "find_integrations":
            return self.find_integrations(args.get("symbol"), limit=int(args.get("limit", 100)))
        if name == "explain_evidence":
            return self.explain_evidence(self._required(args, "symbol"))
        if name == "unresolved":
            return self.context.unresolved(limit=int(args.get("limit", 100)))
        if name == "context_bundle":
            return self.context.context_bundle(
                self._required(args, "symbol"),
                depth=int(args.get("depth", 2)),
                budget=ContextBudget(
                    max_tokens=int(args.get("max_tokens", 4000)),
                    max_nodes=int(args.get("max_nodes", 80)),
                    max_edges=int(args.get("max_edges", 120)),
                ),
            )
        if name == "semantic_diff":
            return diff_store_snapshots(
                self.store,
                self._required(args, "before_snapshot"),
                self._required(args, "after_snapshot"),
            )
        raise KeyError("unknown grounding tool: %s" % name)

    def trace_path(self, source: str, target: str, max_depth: int = 6, direction: str = "outgoing") -> Dict[str, Any]:
        source_node = self.query.resolve(source)
        target_node = self.query.resolve(target)
        max_depth = max(0, min(20, int(max_depth)))
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be outgoing, incoming, or both")
        if source_node.id == target_node.id:
            return {
                "snapshot_id": self.snapshot.snapshot_id,
                "found": True,
                "source": source_node.id,
                "target": target_node.id,
                "path": {"nodes": [source_node.to_dict()], "relationships": []},
            }

        queue = deque([(source_node.id, [])])
        seen: Set[str] = {source_node.id}
        while queue:
            current, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            for edge, neighbor in self._neighbors(current, direction):
                if neighbor in seen:
                    continue
                next_path = path + [edge]
                if neighbor == target_node.id:
                    node_ids = [source_node.id]
                    cursor = source_node.id
                    for item in next_path:
                        cursor = item.target if item.source == cursor else item.source
                        node_ids.append(cursor)
                    return {
                        "snapshot_id": self.snapshot.snapshot_id,
                        "found": True,
                        "source": source_node.id,
                        "target": target_node.id,
                        "direction": direction,
                        "path": {
                            "nodes": [self.graph.node(node_id).to_dict() for node_id in node_ids if self.graph.node(node_id) is not None],
                            "relationships": [item.to_dict() for item in next_path],
                        },
                    }
                seen.add(neighbor)
                queue.append((neighbor, next_path))
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "found": False,
            "status": "unknown",
            "source": source_node.id,
            "target": target_node.id,
            "direction": direction,
            "max_depth": max_depth,
            "note": "No evidenced path was found within the requested stored-graph boundary. This does not prove a path is impossible.",
        }

    def find_integrations(self, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        scoped_node_id = self.query.resolve(symbol).id if symbol else None
        matches: List[SemanticEdge] = []
        for edge in self.graph.edges:
            integration_evidence = any(item.kind.value == "integration_resolution" for item in edge.evidence)
            if edge.kind not in _INTEGRATION_KINDS and not integration_evidence:
                continue
            if scoped_node_id and edge.source != scoped_node_id and edge.target != scoped_node_id:
                continue
            matches.append(edge)
        matches.sort(key=lambda edge: (-float(edge.confidence), edge.kind.value, edge.source, edge.target, edge.id))
        selected = matches[:limit]
        node_ids: Set[str] = set()
        for edge in selected:
            node_ids.add(edge.source)
            node_ids.add(edge.target)
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "scope": scoped_node_id,
            "relationships": [edge.to_dict() for edge in selected],
            "nodes": [self.graph.node(node_id).to_dict() for node_id in sorted(node_ids) if self.graph.node(node_id) is not None],
            "returned_count": len(selected),
            "total_matching": len(matches),
            "truncated": len(matches) > len(selected),
        }

    def explain_evidence(self, symbol: str) -> Dict[str, Any]:
        node = self.query.resolve(symbol)
        outgoing = list(self.graph.outgoing(node.id))
        incoming = list(self.graph.incoming(node.id))
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "symbol": {
                "id": node.id,
                "qualified_name": node.qualified_name,
                "kind": node.kind.value,
                "confidence": node.confidence,
                "confidence_tier": node.confidence_tier.value,
                "evidence": [item.to_dict() for item in node.evidence],
            },
            "relationships": {
                "outgoing": [edge.to_dict() for edge in outgoing],
                "incoming": [edge.to_dict() for edge in incoming],
            },
            "grounding": {
                "known": "Only evidence present in this immutable snapshot is reported.",
                "unknown": "Missing evidence or relationships remain unknown rather than being inferred by this service.",
            },
        }

    def _neighbors(self, node_id: str, direction: str) -> Iterable[Tuple[SemanticEdge, str]]:
        if direction in {"outgoing", "both"}:
            for edge in self.graph.outgoing(node_id):
                yield edge, edge.target
        if direction in {"incoming", "both"}:
            for edge in self.graph.incoming(node_id):
                yield edge, edge.source

    def _with_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(payload)
        result["snapshot_id"] = self.snapshot.snapshot_id
        return result

    @staticmethod
    def _required(arguments: Dict[str, Any], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s is required" % key)
        return value.strip()
