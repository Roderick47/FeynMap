"""Predict graph impact from unified git diffs."""

import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


OUTPUT_CHANGE_IMPACT_FILE = "feyn_change_impact.json"
DEFAULT_IMPACT_DEPTH = 6
BREAKAGE_NODE_TYPES = {"VERTEX", "TRANSFORM", "FRONTEND"}
HIGH_RISK_NODE_TYPES = {"VERTEX", "FRONTEND"}
DEPENDENCY_EDGE_TYPES = {
    "PARTICLE_ENTANGLEMENT",
    "SERIALIZER_ENTANGLEMENT",
    "CALL",
    "OBSERVATION",
    "AJAX",
    "EVENT",
    "VIRTUAL",
    "DEPENDENCY",
}


class ImpactGraphCache:
    """Indexes graph data for reverse dependency impact lookups."""

    def __init__(self, graph_data: Dict[str, Any]) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {
            node["id"]: node for node in graph_data.get("nodes", [])
        }
        self.edges: List[Dict[str, Any]] = graph_data.get("edges", [])
        self.edges_by_target: Dict[str, List[Dict[str, Any]]] = {}
        self.edges_by_source: Dict[str, List[Dict[str, Any]]] = {}

        for edge in self.edges:
            self.edges_by_target.setdefault(edge.get("target", ""), []).append(edge)
            self.edges_by_source.setdefault(edge.get("source", ""), []).append(edge)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Return a node by id."""
        return self.nodes.get(node_id)

    def dependents_of(self, node_id: str) -> List[Dict[str, Any]]:
        """Return incoming edges whose sources depend on the node."""
        return self.edges_by_target.get(node_id, [])

    def dependencies_of(self, node_id: str) -> List[Dict[str, Any]]:
        """Return outgoing edges from a changed node to its dependencies."""
        return self.edges_by_source.get(node_id, [])


def parse_unified_diff(diff_text: str) -> Dict[str, Any]:
    """Parse changed files and new-file changed line numbers from a unified git diff."""
    files: Dict[str, Dict[str, Any]] = {}
    current_file: Optional[str] = None
    old_file: Optional[str] = None
    new_file: Optional[str] = None
    new_line: Optional[int] = None
    old_line: Optional[int] = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            old_file = None
            new_file = None
            current_file = None
            continue

        if raw_line.startswith("--- "):
            old_file = _clean_diff_path(raw_line[4:].strip())
            continue

        if raw_line.startswith("+++ "):
            new_file = _clean_diff_path(raw_line[4:].strip())
            current_file = new_file if new_file != "/dev/null" else old_file
            if current_file and current_file != "/dev/null":
                files.setdefault(current_file, {"changed_lines": set(), "deleted": new_file == "/dev/null"})
            continue

        if current_file is None:
            continue

        hunk_match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw_line)
        if hunk_match:
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(3))
            continue

        if new_line is None or old_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):  # added/modified line
            files[current_file]["changed_lines"].add(new_line)
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):  # deleted line
            files[current_file]["changed_lines"].add(new_line)
            old_line += 1
        else:
            new_line += 1
            old_line += 1

    return {
        path: {
            "changed_lines": sorted(data["changed_lines"]),
            "deleted": data.get("deleted", False),
        }
        for path, data in sorted(files.items())
    }


def load_diff(diff_source: Optional[str]) -> str:
    """Load a diff from a file path, stdin marker, or direct diff string."""
    if diff_source in {None, "-"}:
        return sys.stdin.read()

    source_path = Path(diff_source)
    if source_path.exists():
        return source_path.read_text(encoding="utf-8")

    return diff_source


def predict_change_impact(
    graph_data: Dict[str, Any],
    diff_text: str,
    project_dir: str = ".",
    max_depth: int = DEFAULT_IMPACT_DEPTH,
) -> Dict[str, Any]:
    """
    Given graph data and a git diff, identify touched nodes and reverse dependents.

    FeynMap edges usually point from a consumer to what it uses (for example,
    View -> Model). A model change therefore impacts incoming edge sources, then
    recursively the sources that depend on those sources.
    """
    changed_files = parse_unified_diff(diff_text)
    cache = ImpactGraphCache(graph_data)
    seeds = _find_changed_nodes(graph_data, changed_files, project_dir)
    impacted_nodes, impact_paths = _trace_dependents(cache, seeds, max_depth)
    risk_summary = _summarize_risk(cache, seeds, impacted_nodes, impact_paths, changed_files, max_depth)

    return {
        "changed_files": changed_files,
        "changed_nodes": [_serialize_node(cache.get_node(node_id), "changed") for node_id in sorted(seeds)],
        "impacted_nodes": [
            _serialize_node(cache.get_node(node_id), "impacted", impact_paths.get(node_id, []))
            for node_id in sorted(impacted_nodes - seeds)
        ],
        "impact_paths": [path for node_id in sorted(impact_paths) for path in impact_paths[node_id]],
        "risk_summary": risk_summary,
        "metadata": {
            "purpose": "Predict which graph nodes may break when changed diff lines touch code or templates.",
            "direction": "reverse_dependencies",
            "max_depth": max_depth,
        },
    }


def save_change_impact(report: Dict[str, Any], output_path: str = OUTPUT_CHANGE_IMPACT_FILE) -> None:
    """Write a change impact report to disk."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)


def _find_changed_nodes(
    graph_data: Dict[str, Any],
    changed_files: Dict[str, Any],
    project_dir: str,
) -> Set[str]:
    """Match diff file/line data against node file and source spans."""
    project_path = Path(project_dir).resolve()
    normalized_changes = {
        _normalize_path(path, project_path): set(data.get("changed_lines", []))
        for path, data in changed_files.items()
    }
    seeds: Set[str] = set()

    for node in graph_data.get("nodes", []):
        node_file = node.get("file") or node.get("metadata", {}).get("file")
        if not node_file:
            continue

        normalized_node_file = _normalize_path(node_file, project_path)
        changed_lines = _lookup_changed_lines(normalized_node_file, normalized_changes)
        if changed_lines is None:
            continue

        if _node_overlaps_changed_lines(node, changed_lines):
            seeds.add(node["id"])

    return seeds


def _trace_dependents(
    cache: ImpactGraphCache,
    seeds: Set[str],
    max_depth: int,
) -> Tuple[Set[str], Dict[str, List[Dict[str, Any]]]]:
    """Breadth-first traversal of reverse dependency edges from changed nodes."""
    impacted: Set[str] = set(seeds)
    impact_paths: Dict[str, List[Dict[str, Any]]] = {}
    queue = deque((seed, [seed], [], 0) for seed in sorted(seeds))

    while queue:
        current, node_path, edge_path, depth = queue.popleft()
        if depth >= max_depth:
            continue

        for edge in _ordered_edges(cache.dependents_of(current)):
            if edge.get("type") not in DEPENDENCY_EDGE_TYPES:
                continue

            dependent = edge.get("source")
            if not dependent or dependent in node_path:
                continue

            next_node_path = node_path + [dependent]
            next_edge_path = edge_path + [edge]
            impacted.add(dependent)
            impact_paths.setdefault(dependent, []).append(_serialize_path(next_node_path, next_edge_path, cache))
            queue.append((dependent, next_node_path, next_edge_path, depth + 1))

    return impacted, impact_paths


def _summarize_risk(
    cache: ImpactGraphCache,
    seeds: Set[str],
    impacted_nodes: Set[str],
    impact_paths: Dict[str, List[Dict[str, Any]]],
    changed_files: Dict[str, Any],
    max_depth: int,
) -> Dict[str, Any]:
    """Create a developer-facing risk summary from impacted nodes."""
    impacted_only = impacted_nodes - seeds
    by_type: Dict[str, int] = {}
    breaking_surfaces: List[str] = []

    for node_id in sorted(impacted_only):
        node = cache.get_node(node_id) or {}
        node_type = node.get("type", "UNKNOWN")
        by_type[node_type] = by_type.get(node_type, 0) + 1
        if node_type in BREAKAGE_NODE_TYPES:
            breaking_surfaces.append(node_id)

    high_risk_count = sum(1 for node_id in impacted_only if (cache.get_node(node_id) or {}).get("type") in HIGH_RISK_NODE_TYPES)
    confidence = "high" if seeds else "low"
    if seeds and not impacted_only:
        confidence = "medium"

    return {
        "changed_node_count": len(seeds),
        "impacted_node_count": len(impacted_only),
        "impacted_by_type": dict(sorted(by_type.items())),
        "potential_breaking_surfaces": breaking_surfaces,
        "high_risk_surface_count": high_risk_count,
        "confidence": confidence,
        "notes": _risk_notes(seeds, impacted_only, changed_files, max_depth),
    }


def _risk_notes(seeds: Set[str], impacted_only: Set[str], changed_files: Dict[str, Any], max_depth: int) -> List[str]:
    notes: List[str] = []
    if not changed_files:
        notes.append("No changed files were found in the supplied diff.")
    if changed_files and not seeds:
        notes.append("Changed files did not match graph nodes; rerun FeynMap with the same project root used to create the diff.")
    if seeds and not impacted_only:
        notes.append("Changed nodes were found, but no reverse graph dependents were discovered.")
    notes.append(f"Impact traversal follows reverse dependency edges up to {max_depth} hops.")
    return notes


def _serialize_node(node: Optional[Dict[str, Any]], role: str, paths: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if not node:
        return {"id": "<unknown>", "role": role, "impact_paths": paths or []}

    data = {
        "id": node.get("id"),
        "type": node.get("type"),
        "file": node.get("file"),
        "line_start": node.get("line_start"),
        "line_end": node.get("line_end"),
        "role": role,
    }
    if paths is not None:
        data["impact_paths"] = paths
    return data


def _serialize_path(node_path: List[str], edge_path: List[Dict[str, Any]], cache: ImpactGraphCache) -> Dict[str, Any]:
    return {
        "nodes": [_serialize_node(cache.get_node(node_id), "path") for node_id in node_path],
        "edges": [
            {"source": edge.get("source"), "target": edge.get("target"), "type": edge.get("type")}
            for edge in edge_path
        ],
        "summary": " <- ".join(node_path),
    }


def _node_overlaps_changed_lines(node: Dict[str, Any], changed_lines: Set[int]) -> bool:
    if not changed_lines:
        return True

    start = node.get("line_start") or node.get("metadata", {}).get("line_start")
    end = node.get("line_end") or node.get("metadata", {}).get("line_end")
    if start is None or end is None:
        return True

    # Added lines in a diff can land immediately after the AST span that was
    # parsed from the post-change working tree or, in tests, from a pre-change
    # fixture. Treat the adjacent line as an overlap so appending a model field
    # still marks the model as changed.
    return any(start <= line <= end + 1 for line in changed_lines)


def _ordered_edges(edges: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(edges, key=lambda edge: (edge.get("source", ""), edge.get("type", ""), edge.get("target", "")))


def _clean_diff_path(path: str) -> str:
    if path == "/dev/null":
        return path
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _normalize_path(path: str, project_path: Path) -> str:
    raw_path = Path(path)
    try:
        if raw_path.is_absolute():
            return str(raw_path.resolve().relative_to(project_path)).replace("\\", "/")
    except ValueError:
        pass
    return str(raw_path).replace("\\", "/")


def _lookup_changed_lines(node_file: str, changes: Dict[str, Set[int]]) -> Optional[Set[int]]:
    if node_file in changes:
        return changes[node_file]

    for changed_file, lines in changes.items():
        if node_file.endswith(changed_file) or changed_file.endswith(node_file):
            return lines

    return None
