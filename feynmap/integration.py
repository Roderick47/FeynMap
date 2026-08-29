"""Cross-language integration contracts and repository-level resolution.

Language and framework adapters emit small, language-neutral integration
contracts on semantic nodes. The resolver connects compatible contracts after
all language graphs have been merged, producing one cohesive application graph.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode

CONTRACT_KEY = "integration_contracts"


def add_contract(
    node: SemanticNode,
    kind: str,
    target: str,
    confidence: float = 1.0,
    **fields: Any
) -> None:
    """Attach a language-neutral integration boundary fact to a node."""
    if not target:
        return
    payload: Dict[str, Any] = {
        "kind": str(kind),
        "target": str(target),
        "confidence": max(0.0, min(1.0, float(confidence))),
    }
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    contracts = node.attributes.setdefault(CONTRACT_KEY, [])
    if not isinstance(contracts, list):
        contracts = []
        node.attributes[CONTRACT_KEY] = contracts
    fingerprint = _contract_fingerprint(payload)
    if not any(_contract_fingerprint(item) == fingerprint for item in contracts if isinstance(item, dict)):
        contracts.append(payload)


def contracts(node: SemanticNode, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    raw = node.attributes.get(CONTRACT_KEY, [])
    items = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    return [item for item in items if kind is None or item.get("kind") == kind]


class IntegrationResolver:
    """Resolve language-neutral integration contracts across a unified graph."""

    CONTRACT_PAIRS: Sequence[Tuple[str, str, EdgeKind]] = (
        ("http_client", "http_server", EdgeKind.REQUESTS),
        ("websocket_client", "websocket_server", EdgeKind.CONNECTS_TO),
        ("rpc_client", "rpc_server", EdgeKind.REQUESTS),
        ("queue_publish", "queue_subscribe", EdgeKind.EMITS),
        ("process_spawn", "cli_entrypoint", EdgeKind.SPAWNS),
        ("ffi_import", "ffi_export", EdgeKind.INVOKES),
        ("deep_link", "app_route", EdgeKind.ROUTES_TO),
        ("ipc_send", "ipc_receive", EdgeKind.FLOWS_TO),
        ("database_client", "database_server", EdgeKind.CONNECTS_TO),
    )

    def resolve(self, graph: SemanticGraph) -> SemanticGraph:
        edge_keys = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
        resolved = 0
        by_kind: Dict[str, int] = {}

        resolved += self._resolve_template_renders(graph, edge_keys, by_kind)
        resolved += self._resolve_script_loads(graph, edge_keys, by_kind)
        resolved += self._resolve_event_handlers(graph, edge_keys, by_kind)

        for client_kind, server_kind, edge_kind in self.CONTRACT_PAIRS:
            count = self._resolve_pair(graph, edge_keys, client_kind, server_kind, edge_kind)
            if count:
                resolved += count
                by_kind["%s->%s" % (client_kind, server_kind)] = count

        file_count = self._resolve_file_flow(graph, edge_keys)
        if file_count:
            resolved += file_count
            by_kind["file_write->file_read"] = file_count

        unresolved = self._unresolved_contracts(graph)
        graph.metadata["integration"] = {
            "resolved_edges": resolved,
            "resolved_by_kind": by_kind,
            "unresolved_contracts": len(unresolved),
            "unresolved_sample": unresolved[:50],
        }
        graph.validate()
        return graph

    def _resolve_template_renders(self, graph: SemanticGraph, edge_keys: set, by_kind: Dict[str, int]) -> int:
        html_nodes = [node for node in graph.nodes if node.language == "html"]
        count = 0
        for source in graph.nodes:
            for contract in contracts(source, "template_render"):
                target_name = _normalize_resource(contract.get("target", ""))
                target = _best_path_match(html_nodes, target_name)
                if target and self._connect(graph, edge_keys, source, target, EdgeKind.RENDERS, contract, "template_render"):
                    count += 1
        if count:
            by_kind["template_render->html"] = count
        return count

    def _resolve_script_loads(self, graph: SemanticGraph, edge_keys: set, by_kind: Dict[str, int]) -> int:
        js_nodes = [node for node in graph.nodes if node.language == "javascript" and node.location]
        count = 0
        for source in graph.nodes:
            for contract in contracts(source, "script_load"):
                target_name = _normalize_resource(contract.get("target", ""))
                target = _best_path_match(js_nodes, target_name, prefer_modules=True)
                if target and self._connect(graph, edge_keys, source, target, EdgeKind.LOADS, contract, "script_load"):
                    count += 1
        if count:
            by_kind["html->javascript"] = count
        return count

    def _resolve_event_handlers(self, graph: SemanticGraph, edge_keys: set, by_kind: Dict[str, int]) -> int:
        js_symbols = [node for node in graph.nodes if node.language == "javascript" and node.kind.value in {"function", "method"}]
        loaded_paths: Dict[str, List[str]] = {}
        for edge in graph.edges:
            if edge.kind == EdgeKind.LOADS:
                target = graph.node(edge.target)
                if target and target.location:
                    loaded_paths.setdefault(edge.source, []).append(target.location.path)

        count = 0
        for source in graph.nodes:
            for contract in contracts(source, "event_handler"):
                name = str(contract.get("target", "")).strip()
                candidates = [node for node in js_symbols if node.name == name or (node.qualified_name or "").endswith("." + name)]
                preferred_paths = loaded_paths.get(source.id, [])
                if preferred_paths:
                    preferred = [node for node in candidates if node.location and node.location.path in preferred_paths]
                    candidates = preferred or candidates
                if len(candidates) == 1 and self._connect(graph, edge_keys, source, candidates[0], EdgeKind.INVOKES, contract, "event_handler"):
                    count += 1
        if count:
            by_kind["html_event->javascript"] = count
        return count

    def _resolve_pair(
        self,
        graph: SemanticGraph,
        edge_keys: set,
        source_kind: str,
        target_kind: str,
        edge_kind: EdgeKind,
    ) -> int:
        sources = [(node, item) for node in graph.nodes for item in contracts(node, source_kind)]
        targets = [(node, item) for node in graph.nodes for item in contracts(node, target_kind)]
        count = 0
        for source_node, source_contract in sources:
            matches: List[Tuple[SemanticNode, Dict[str, Any]]] = []
            for target_node, target_contract in targets:
                if source_node.id == target_node.id:
                    continue
                if _contracts_match(source_contract, target_contract, source_kind, target_kind):
                    matches.append((target_node, target_contract))
            if len(matches) == 1:
                target_node, target_contract = matches[0]
                confidence = min(
                    float(source_contract.get("confidence", 0.8)),
                    float(target_contract.get("confidence", 0.8)),
                )
                if self._connect(
                    graph,
                    edge_keys,
                    source_node,
                    target_node,
                    edge_kind,
                    source_contract,
                    "%s->%s" % (source_kind, target_kind),
                    confidence=confidence,
                    target_contract=target_contract,
                ):
                    count += 1
        return count

    def _resolve_file_flow(self, graph: SemanticGraph, edge_keys: set) -> int:
        writers = [(node, item) for node in graph.nodes for item in contracts(node, "file_write")]
        readers = [(node, item) for node in graph.nodes for item in contracts(node, "file_read")]
        count = 0
        for writer, write_contract in writers:
            resource = _normalize_resource(write_contract.get("target", ""))
            if not resource:
                continue
            for reader, read_contract in readers:
                if writer.id == reader.id:
                    continue
                if resource != _normalize_resource(read_contract.get("target", "")):
                    continue
                if self._connect(graph, edge_keys, writer, reader, EdgeKind.FLOWS_TO, write_contract, "file_flow", target_contract=read_contract):
                    count += 1
        return count

    def _connect(
        self,
        graph: SemanticGraph,
        edge_keys: set,
        source: SemanticNode,
        target: SemanticNode,
        kind: EdgeKind,
        source_contract: Dict[str, Any],
        detector_suffix: str,
        confidence: Optional[float] = None,
        target_contract: Optional[Dict[str, Any]] = None,
    ) -> bool:
        key = (source.id, target.id, kind.value)
        if key in edge_keys:
            return False
        score = float(confidence if confidence is not None else source_contract.get("confidence", 0.9))
        score = max(0.0, min(1.0, score))
        detail = "%s integration matched %s -> %s" % (detector_suffix, source.name, target.name)
        evidence = Evidence(EvidenceKind.INTEGRATION, "integration.%s" % detector_suffix, detail, source.location, score)
        raw = "%s|%s|%s|%s" % (source.id, target.id, kind.value, detector_suffix)
        edge = SemanticEdge(
            id="edge:integration:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
            source=source.id,
            target=target.id,
            kind=kind,
            confidence=score,
            evidence=[evidence],
            attributes={
                "integration": {
                    "source_contract": source_contract,
                    "target_contract": target_contract,
                    "cross_language": source.language != target.language,
                }
            },
        )
        graph.add_edge(edge)
        edge_keys.add(key)
        return True

    def _unresolved_contracts(self, graph: SemanticGraph) -> List[Dict[str, Any]]:
        connected: set = set()
        for edge in graph.edges:
            if edge.attributes.get("integration"):
                connected.add(edge.source)
                connected.add(edge.target)
        result: List[Dict[str, Any]] = []
        for node in graph.nodes:
            for item in contracts(node):
                if node.id not in connected and item.get("kind") not in {"config_read"}:
                    result.append({"node": node.id, "kind": item.get("kind"), "target": item.get("target")})
        return result


def _contracts_match(source: Dict[str, Any], target: Dict[str, Any], source_kind: str, target_kind: str) -> bool:
    source_target = str(source.get("target", ""))
    target_target = str(target.get("target", ""))
    if source_kind == "http_client" and target_kind == "http_server":
        if not _http_route_matches(source_target, target_target):
            return False
        source_method = str(source.get("method") or "GET").upper()
        target_methods = target.get("methods") or [target.get("method") or "GET"]
        methods = {str(item).upper() for item in target_methods}
        return source_method in methods or "ANY" in methods
    if source_kind == "websocket_client" and target_kind == "websocket_server":
        return _http_route_matches(source_target, target_target)
    return _normalize_channel(source_target) == _normalize_channel(target_target)


def _http_route_matches(client: str, server: str) -> bool:
    client_path = _url_path(client)
    server_path = _url_path(server)
    if not client_path or not server_path:
        return False
    if client_path == server_path:
        return True
    escaped = re.escape(server_path)
    escaped = re.sub(r"\\\{[^/]+?\\\}", r"[^/]+", escaped)
    escaped = re.sub(r"\\<(?:(?:int|str|slug|uuid|path):)?[^>]+\\>", r"[^/]+", escaped)
    try:
        return re.fullmatch(escaped.rstrip("/") + "/?", client_path) is not None
    except re.error:
        return False


def _url_path(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]+", "", text)
    text = text.split("?", 1)[0].split("#", 1)[0]
    if not text:
        return "/"
    if not text.startswith("/"):
        text = "/" + text
    return re.sub(r"/+", "/", text).rstrip("/") or "/"


def _normalize_resource(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"^https?://[^/]+", "", text)
    text = text.split("?", 1)[0].split("#", 1)[0]
    text = re.sub(r"^\{\%\s*static\s+['\"]([^'\"]+)['\"]\s*\%\}$", r"\1", text)
    while text.startswith("../"):
        text = text[3:]
    return text.lstrip("./")


def _normalize_channel(value: str) -> str:
    return str(value or "").strip().lower().replace("\\", "/")


def _best_path_match(nodes: Iterable[SemanticNode], target: str, prefer_modules: bool = False) -> Optional[SemanticNode]:
    normalized = _normalize_resource(target)
    if not normalized:
        return None
    candidates: List[SemanticNode] = []
    for node in nodes:
        if not node.location:
            continue
        path = _normalize_resource(node.location.path)
        if path == normalized or path.endswith("/" + normalized) or normalized.endswith("/" + path):
            candidates.append(node)
        elif PurePosixPath(path).name == PurePosixPath(normalized).name:
            candidates.append(node)
    if prefer_modules:
        module_candidates = [node for node in candidates if node.kind.value == "module"]
        if module_candidates:
            candidates = module_candidates
    return candidates[0] if len(candidates) == 1 else None


def _contract_fingerprint(payload: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        payload.get("kind"),
        payload.get("target"),
        payload.get("method"),
        tuple(payload.get("methods", [])) if isinstance(payload.get("methods"), list) else payload.get("methods"),
        payload.get("channel"),
    )
