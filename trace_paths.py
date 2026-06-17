"""Branch-preserving interaction paths for FeynMap output."""

from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .feyn_notation import FeynNotator
except ImportError:
    from feyn_notation import FeynNotator


DEFAULT_EDGE_PRIORITY = [
    "SERIALIZER_ENTANGLEMENT",
    "CALL",
    "PARTICLE_ENTANGLEMENT",
    "EVENT",
    "AJAX",
    "DEPENDENCY",
    "VIRTUAL",
    "OBSERVATION",
    "CONTAINS",
]
TERMINAL_NODE_TYPES = {"PARTICLE", "TRANSFORM", "AJAX", "DEPENDENCY"}
PROPAGATOR_HTTP_METADATA = {"mass": 0.1, "energy": 1.0, "coupling": 0.9}


def generate_branch_preserving_ledger(
    node: Dict[str, Any],
    cache: Any,
    interaction_type: str,
    max_depth: int,
) -> Tuple[str, Dict[str, Any]]:
    """Return readable per-path notation plus a canonical graph slice."""
    source_id = node["id"]
    paths = enumerate_interaction_paths(source_id, cache, max_depth)
    rendered_paths = []

    for index, path in enumerate(paths, start=1):
        trace, metadata_map = _notation_trace(path, cache, interaction_type)
        rendered_paths.append(
            {
                "id": f"path_{index:03d}",
                "notation": FeynNotator.generate_enhanced_string(trace, metadata_map),
                "legacy_notation": FeynNotator.generate_string(trace),
                "node_ids": path["node_ids"],
                "edges": path["edges"],
                "termination": path["termination"],
                "cycle_to": path.get("cycle_to"),
                "truncated": path["termination"] == "max_depth",
                "diagram": FeynNotator.generate_diagram_data(trace, metadata_map),
            }
        )

    legacy = "\n".join(
        f"PATH {index}: {item['legacy_notation']}"
        for index, item in enumerate(rendered_paths, start=1)
    )
    graph_slice = build_graph_slice(paths, cache)
    enhanced = {
        "notation": "\n".join(
            f"PATH {index}: {item['notation']}"
            for index, item in enumerate(rendered_paths, start=1)
        ),
        "paths": rendered_paths,
        "graph": graph_slice,
        "metadata": {
            "interaction_type": interaction_type,
            "max_trace_depth": max_depth,
            "path_count": len(rendered_paths),
            "branching": len(rendered_paths) > 1,
            "truncated_path_count": sum(1 for item in rendered_paths if item["truncated"]),
            "cycle_path_count": sum(
                1 for item in rendered_paths if item["termination"] == "cycle"
            ),
            "representation": "branch_preserving_paths",
        },
    }
    return legacy, enhanced


def enumerate_interaction_paths(source_id: str, cache: Any, max_depth: int) -> List[Dict[str, Any]]:
    """Enumerate deterministic root-to-leaf paths without flattening branches."""
    paths: List[Dict[str, Any]] = []
    _walk(
        current=source_id,
        cache=cache,
        remaining_depth=max_depth,
        node_ids=[source_id],
        edges=[],
        visited={source_id},
        paths=paths,
    )
    if not paths:
        paths.append({"node_ids": [source_id], "edges": [], "termination": "leaf"})
    return paths


def build_graph_slice(paths: List[Dict[str, Any]], cache: Any) -> Dict[str, Any]:
    """Build a deduplicated canonical graph covering all enumerated paths."""
    node_ids: Set[str] = set()
    edges_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for path in paths:
        node_ids.update(path["node_ids"])
        for edge in path["edges"]:
            key = (edge.get("source", ""), edge.get("target", ""), edge.get("type", ""))
            edges_by_key[key] = edge

    nodes = []
    for node_id in sorted(node_ids):
        node = cache.get_node(node_id)
        if node:
            nodes.append(node)
        else:
            nodes.append({"id": node_id, "type": "UNKNOWN", "metadata": {}})

    return {
        "root": paths[0]["node_ids"][0] if paths else None,
        "nodes": nodes,
        "edges": [edges_by_key[key] for key in sorted(edges_by_key)],
    }


def _walk(
    current: str,
    cache: Any,
    remaining_depth: int,
    node_ids: List[str],
    edges: List[Dict[str, Any]],
    visited: Set[str],
    paths: List[Dict[str, Any]],
) -> None:
    node = cache.get_node(current)
    if node and node.get("type") in TERMINAL_NODE_TYPES:
        paths.append({"node_ids": node_ids, "edges": edges, "termination": "terminal"})
        return

    outgoing = _ordered_edges(cache.get_edges(current))
    if not outgoing:
        paths.append({"node_ids": node_ids, "edges": edges, "termination": "leaf"})
        return

    if remaining_depth <= 0:
        paths.append({"node_ids": node_ids, "edges": edges, "termination": "max_depth"})
        return

    for edge in outgoing:
        target = edge.get("target")
        if not target:
            continue
        if target in visited:
            paths.append(
                {
                    "node_ids": list(node_ids),
                    "edges": edges + [dict(edge)],
                    "termination": "cycle",
                    "cycle_to": target,
                }
            )
            continue
        _walk(
            current=target,
            cache=cache,
            remaining_depth=remaining_depth - 1,
            node_ids=node_ids + [target],
            edges=edges + [dict(edge)],
            visited=visited | {target},
            paths=paths,
        )


def _notation_trace(
    path: Dict[str, Any], cache: Any, interaction_type: str
) -> Tuple[List[Tuple[str, str]], Dict[int, Dict[str, Any]]]:
    trace: List[Tuple[str, str]] = []
    metadata_map: Dict[int, Dict[str, Any]] = {}

    if interaction_type == "backend":
        trace.append(("PROPAGATOR_HTTP", "URL"))
        metadata_map[0] = PROPAGATOR_HTTP_METADATA

    edge_by_target = {edge.get("target"): edge for edge in path["edges"]}
    for node_id in path["node_ids"]:
        node = cache.get_node(node_id)
        edge = edge_by_target.get(node_id)
        role = _role_for_node(node, edge)
        trace.append((role, node_id))
        metadata_map[len(trace) - 1] = node.get("metadata", {}) if node else {}

    return trace, metadata_map


def _role_for_node(
    node: Optional[Dict[str, Any]], edge: Optional[Dict[str, Any]]
) -> str:
    edge_type = edge.get("type") if edge else None
    if edge_type == "SERIALIZER_ENTANGLEMENT":
        return "TRANSFORM"
    if edge_type == "PARTICLE_ENTANGLEMENT":
        return "PARTICLE"
    if edge_type == "AJAX":
        return "PROPAGATOR_AJAX"
    if node:
        return node.get("type", "MEDIATOR")
    return "MEDIATOR"


def _ordered_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    priority = {edge_type: index for index, edge_type in enumerate(DEFAULT_EDGE_PRIORITY)}
    return sorted(
        edges,
        key=lambda edge: (
            priority.get(edge.get("type"), len(priority)),
            edge.get("target", ""),
        ),
    )
