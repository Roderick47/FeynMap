"""Evidence-based reachability analysis for FeynMap graphs."""

import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

OUTPUT_REACHABILITY_FILE = "feyn_reachability.json"

ENTRY_NODE_TYPES = {"VERTEX", "FRONTEND"}
FRAMEWORK_ENTRY_FILES = {
    "signals.py",
    "tasks.py",
    "middleware.py",
    "admin.py",
    "apps.py",
    "consumers.py",
    "receivers.py",
}
FRAMEWORK_ENTRY_PATH_PARTS = {
    "management/commands",
    "migrations",
}
FRAMEWORK_HOOK_NAMES = {
    "ready",
    "dispatch",
    "handle",
    "process_request",
    "process_response",
    "process_view",
    "process_exception",
    "get",
    "post",
    "put",
    "patch",
    "delete",
}
DYNAMIC_REFERENCE_HINTS = {
    "registry",
    "plugin",
    "handler",
    "receiver",
    "signal",
    "callback",
    "factory",
    "command",
}


def analyze_reachability(graph_data: Dict[str, Any]) -> Dict[str, Any]:
    """Classify graph nodes using explicit entry points and graph traversal."""
    nodes = {node["id"]: node for node in graph_data.get("nodes", [])}
    outgoing = _outgoing_edges(graph_data.get("edges", []))
    incoming = _incoming_edges(graph_data.get("edges", []))

    entry_points: Dict[str, Dict[str, Any]] = {}
    protected_nodes: Dict[str, Dict[str, Any]] = {}

    for node_id, node in nodes.items():
        entry = _entry_point_evidence(node)
        if entry:
            entry_points[node_id] = entry
            continue

        protected = _protected_classification(node)
        if protected:
            protected_nodes[node_id] = protected

    reachable, reached_from = _traverse(entry_points, outgoing)
    classifications: Dict[str, Dict[str, Any]] = {}

    for node_id, node in nodes.items():
        if node_id in entry_points:
            classifications[node_id] = {
                "classification": entry_points[node_id]["classification"],
                "confidence": entry_points[node_id]["confidence"],
                "evidence": entry_points[node_id]["evidence"],
                "reachable": True,
                "reached_from": [node_id],
            }
        elif node_id in reachable:
            classifications[node_id] = {
                "classification": "reachable",
                "confidence": 0.95,
                "evidence": ["Reachable from a recognized entry point through graph edges."],
                "reachable": True,
                "reached_from": sorted(reached_from.get(node_id, set())),
            }
        elif node_id in protected_nodes:
            protected = protected_nodes[node_id]
            classifications[node_id] = {
                "classification": protected["classification"],
                "confidence": protected["confidence"],
                "evidence": protected["evidence"],
                "reachable": False,
                "reached_from": [],
            }
        else:
            classifications[node_id] = _classify_unreached(
                node_id,
                node,
                incoming.get(node_id, []),
                outgoing.get(node_id, []),
            )

    summary: Dict[str, int] = {}
    for item in classifications.values():
        key = item["classification"]
        summary[key] = summary.get(key, 0) + 1

    return {
        "entry_points": [
            {
                "id": node_id,
                **entry_points[node_id],
            }
            for node_id in sorted(entry_points)
        ],
        "nodes": [
            {
                "id": node_id,
                "name": nodes[node_id].get("name", node_id),
                "type": nodes[node_id].get("type"),
                "file": nodes[node_id].get("file"),
                **classifications[node_id],
            }
            for node_id in sorted(nodes)
        ],
        "summary": summary,
        "metadata": {
            "node_count": len(nodes),
            "entry_point_count": len(entry_points),
            "reachable_count": sum(1 for item in classifications.values() if item["reachable"]),
            "purpose": (
                "Evidence-based reachability classification. Nodes are not called dead code "
                "merely because they are absent from generated ledgers."
            ),
        },
    }


def save_reachability(report: Dict[str, Any], output_path: str = OUTPUT_REACHABILITY_FILE) -> None:
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=4)


def possibly_unreachable_nodes(report: Dict[str, Any]) -> Set[str]:
    """Return only nodes that have strong evidence of being unreachable."""
    return {
        item["id"]
        for item in report.get("nodes", [])
        if item.get("classification") == "possibly_unreachable"
        and item.get("confidence", 0.0) >= 0.8
    }


def _outgoing_edges(edges: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        result.setdefault(edge.get("source", ""), []).append(edge)
    return result


def _incoming_edges(edges: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        result.setdefault(edge.get("target", ""), []).append(edge)
    return result


def _traverse(
    entry_points: Dict[str, Dict[str, Any]],
    outgoing: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Set[str], Dict[str, Set[str]]]:
    reachable: Set[str] = set(entry_points)
    reached_from: Dict[str, Set[str]] = {node_id: {node_id} for node_id in entry_points}
    queue = deque((node_id, node_id) for node_id in entry_points)

    while queue:
        current, origin = queue.popleft()
        for edge in outgoing.get(current, []):
            target = edge.get("target")
            if not target:
                continue
            reached_from.setdefault(target, set()).add(origin)
            if target in reachable:
                continue
            reachable.add(target)
            queue.append((target, origin))

    return reachable, reached_from


def _entry_point_evidence(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    node_type = node.get("type")
    if node_type in ENTRY_NODE_TYPES:
        label = "http_entry_point" if node_type == "VERTEX" else "frontend_entry_point"
        return {
            "classification": label,
            "confidence": 1.0,
            "evidence": [f"Node type {node_type} is a recognized application entry surface."],
        }

    path = _normalized_path(node.get("file"))
    name = str(node.get("name") or node.get("id") or "").lower()

    if path.endswith("/__main__.py") or path.endswith("/manage.py") or path.endswith("/cli.py"):
        return {
            "classification": "cli_entry_point",
            "confidence": 0.95,
            "evidence": [f"Source path {path} is a conventional executable entry point."],
        }

    if name == "main" and path.endswith(".py"):
        return {
            "classification": "cli_entry_point",
            "confidence": 0.85,
            "evidence": ["Top-level callable named main is a likely executable entry point."],
        }
    return None


def _protected_classification(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    path = _normalized_path(node.get("file"))
    name = str(node.get("name") or node.get("id") or "").lower()

    if _is_test_path(path) or name.startswith("test_"):
        return {
            "classification": "test_only",
            "confidence": 0.95,
            "evidence": ["Node is defined in test code or follows test naming conventions."],
        }

    filename = Path(path).name if path else ""
    if filename in FRAMEWORK_ENTRY_FILES or any(part in path for part in FRAMEWORK_ENTRY_PATH_PARTS):
        return {
            "classification": "framework_entry_point",
            "confidence": 0.85,
            "evidence": [f"Source path {path} is conventionally loaded by the framework."],
        }

    if name in FRAMEWORK_HOOK_NAMES:
        return {
            "classification": "framework_hook",
            "confidence": 0.75,
            "evidence": [f"Callable name {name} matches a conventional framework hook."],
        }

    if path.endswith("/__init__.py") and not name.startswith("_"):
        return {
            "classification": "public_api_candidate",
            "confidence": 0.7,
            "evidence": ["Public symbol in __init__.py may be exported for external callers."],
        }

    lowered = f"{name} {path}".lower()
    if any(hint in lowered for hint in DYNAMIC_REFERENCE_HINTS):
        return {
            "classification": "dynamic_reference_suspected",
            "confidence": 0.65,
            "evidence": ["Name or path suggests registration, callbacks, plugins, or dynamic loading."],
        }
    return None


def _classify_unreached(
    node_id: str,
    node: Dict[str, Any],
    incoming: List[Dict[str, Any]],
    outgoing: List[Dict[str, Any]],
) -> Dict[str, Any]:
    imported = bool(node.get("imported"))
    node_type = node.get("type")

    if imported or str(node_id).startswith(("dependency:", "ajax:", "unresolved:")):
        return {
            "classification": "external_or_unresolved",
            "confidence": 0.9,
            "evidence": ["Node represents an external, imported, or unresolved symbol."],
            "reachable": False,
            "reached_from": [],
        }

    if not incoming and not outgoing and node_type in {"MEDIATOR", "TRANSFORM", "PARTICLE"}:
        return {
            "classification": "possibly_unreachable",
            "confidence": 0.82,
            "evidence": [
                "No incoming or outgoing graph edges were found.",
                "No framework, test, public API, or dynamic-loading evidence was detected.",
            ],
            "reachable": False,
            "reached_from": [],
        }

    if not incoming:
        return {
            "classification": "isolated_root",
            "confidence": 0.55,
            "evidence": [
                "Node has no incoming graph edges but may be called dynamically or externally."
            ],
            "reachable": False,
            "reached_from": [],
        }

    return {
        "classification": "unknown",
        "confidence": 0.4,
        "evidence": [
            "Node was not reached from known entry points, but existing graph evidence is insufficient to call it unused."
        ],
        "reachable": False,
        "reached_from": [],
    }


def _is_test_path(path: str) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    filename = Path(path).name.lower()
    return "tests" in parts or "test" in parts or filename.startswith("test_") or filename.endswith("_test.py")


def _normalized_path(value: Any) -> str:
    if not value:
        return ""
    return str(value).replace("\\", "/")
