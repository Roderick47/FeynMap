"""Evidence-backed change-impact prediction for FeynMap."""

from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    from .change_impact import (
        DEFAULT_IMPACT_DEPTH,
        ImpactGraphCache,
        parse_unified_diff,
        save_change_impact,
    )
except ImportError:
    from change_impact import (
        DEFAULT_IMPACT_DEPTH,
        ImpactGraphCache,
        parse_unified_diff,
        save_change_impact,
    )


EDGE_CONFIDENCE = {
    "PARTICLE_ENTANGLEMENT": 0.98,
    "SERIALIZER_ENTANGLEMENT": 0.98,
    "CALL": 0.88,
    "AJAX": 0.82,
    "DEPENDENCY": 0.78,
    "EVENT": 0.72,
    "OBSERVATION": 0.65,
    "VIRTUAL": 0.58,
}
DEPENDENCY_EDGE_TYPES = set(EDGE_CONFIDENCE)
BREAKAGE_NODE_TYPES = {"VERTEX", "TRANSFORM", "FRONTEND"}


def predict_change_impact(
    graph_data: Dict[str, Any],
    diff_text: str,
    project_dir: str = ".",
    max_depth: int = DEFAULT_IMPACT_DEPTH,
) -> Dict[str, Any]:
    """Predict impact while making uncertainty and graph limitations explicit."""
    changed_files = parse_unified_diff(diff_text)
    cache = ImpactGraphCache(graph_data)
    seeds, unmatched_files = _find_changed_nodes_with_evidence(
        graph_data, changed_files, project_dir
    )
    impacted, paths = _trace_dependents_with_confidence(cache, seeds, max_depth)
    graph_quality = _graph_quality_diagnostics(
        graph_data, seeds, unmatched_files, impacted, cache
    )

    changed_nodes = [
        _serialize_changed_node(cache.get_node(node_id), seeds[node_id])
        for node_id in sorted(seeds)
    ]
    impacted_nodes = [
        _serialize_impacted_node(cache.get_node(node_id), paths[node_id])
        for node_id in sorted(impacted)
        if node_id not in seeds
    ]

    return {
        "changed_files": changed_files,
        "changed_nodes": changed_nodes,
        "impacted_nodes": impacted_nodes,
        "impact_paths": [
            path
            for node_id in sorted(paths)
            for path in sorted(
                paths[node_id], key=lambda item: item["confidence"], reverse=True
            )
        ],
        "risk_summary": _summarize_risk(
            changed_nodes, impacted_nodes, graph_quality, max_depth
        ),
        "graph_quality": graph_quality,
        "metadata": {
            "purpose": (
                "Evidence-backed change-impact prediction. Results describe "
                "potential impact, not guaranteed breakage."
            ),
            "direction": "reverse_dependencies",
            "max_depth": max_depth,
            "confidence_model": "seed confidence multiplied by edge evidence and hop decay",
        },
    }


def _find_changed_nodes_with_evidence(
    graph_data: Dict[str, Any],
    changed_files: Dict[str, Any],
    project_dir: str,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    project_path = Path(project_dir).resolve()
    normalized_changes = {
        _normalize_path(path, project_path): data
        for path, data in changed_files.items()
    }
    seeds: Dict[str, Dict[str, Any]] = {}
    matched_files: Set[str] = set()

    for node in graph_data.get("nodes", []):
        node_file = node.get("file") or node.get("metadata", {}).get("file")
        if not node_file:
            continue
        normalized_node_file = _normalize_path(node_file, project_path)
        match = _lookup_change(normalized_node_file, normalized_changes)
        if match is None:
            continue

        changed_file, change = match
        changed_lines = set(change.get("changed_lines", []))
        overlap = _overlap_evidence(node, changed_lines)
        if overlap is None:
            continue

        matched_files.add(changed_file)
        confidence, evidence = overlap
        if change.get("deleted"):
            confidence = min(confidence, 0.75)
            evidence.append("Source file was deleted; node span could not be revalidated.")

        seeds[node["id"]] = {
            "confidence": confidence,
            "evidence": evidence,
            "changed_file": changed_file,
            "changed_lines": sorted(changed_lines),
        }

    unmatched = sorted(set(normalized_changes) - matched_files)
    return seeds, unmatched


def _trace_dependents_with_confidence(
    cache: ImpactGraphCache,
    seeds: Dict[str, Dict[str, Any]],
    max_depth: int,
) -> Tuple[Set[str], Dict[str, List[Dict[str, Any]]]]:
    impacted: Set[str] = set(seeds)
    paths: Dict[str, List[Dict[str, Any]]] = {}
    queue = deque()

    for seed_id in sorted(seeds):
        seed_confidence = seeds[seed_id]["confidence"]
        queue.append((seed_id, [seed_id], [], seed_confidence, 0))

    while queue:
        current, node_path, edge_path, confidence, depth = queue.popleft()
        if depth >= max_depth:
            continue

        for edge in _ordered_edges(cache.dependents_of(current)):
            edge_type = edge.get("type")
            if edge_type not in DEPENDENCY_EDGE_TYPES:
                continue
            dependent = edge.get("source")
            if not dependent or dependent in node_path:
                continue

            edge_confidence = _edge_confidence(edge)
            hop_decay = 0.96 if depth == 0 else 0.92
            next_confidence = round(confidence * edge_confidence * hop_decay, 4)
            next_node_path = node_path + [dependent]
            next_edge_path = edge_path + [edge]
            path = _serialize_path(
                next_node_path,
                next_edge_path,
                cache,
                next_confidence,
                depth + 1,
            )
            impacted.add(dependent)
            paths.setdefault(dependent, []).append(path)

            if next_confidence >= 0.2:
                queue.append(
                    (
                        dependent,
                        next_node_path,
                        next_edge_path,
                        next_confidence,
                        depth + 1,
                    )
                )

    return impacted, paths


def _edge_confidence(edge: Dict[str, Any]) -> float:
    explicit = edge.get("confidence")
    if isinstance(explicit, (int, float)):
        return max(0.0, min(1.0, float(explicit)))
    return EDGE_CONFIDENCE.get(edge.get("type"), 0.5)


def _serialize_path(
    node_path: List[str],
    edge_path: List[Dict[str, Any]],
    cache: ImpactGraphCache,
    confidence: float,
    depth: int,
) -> Dict[str, Any]:
    return {
        "nodes": [_node_identity(cache.get_node(node_id)) for node_id in node_path],
        "edges": [
            {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "type": edge.get("type"),
                "confidence": _edge_confidence(edge),
                "resolution": edge.get("resolution"),
            }
            for edge in edge_path
        ],
        "summary": " <- ".join(node_path),
        "depth": depth,
        "confidence": round(confidence, 3),
        "confidence_label": _confidence_label(confidence),
        "evidence": _path_evidence(edge_path),
    }


def _serialize_changed_node(
    node: Optional[Dict[str, Any]], evidence: Dict[str, Any]
) -> Dict[str, Any]:
    result = _node_identity(node)
    result.update(
        {
            "role": "changed",
            "confidence": round(evidence["confidence"], 3),
            "confidence_label": _confidence_label(evidence["confidence"]),
            "evidence": evidence["evidence"],
            "changed_file": evidence["changed_file"],
            "changed_lines": evidence["changed_lines"],
        }
    )
    return result


def _serialize_impacted_node(
    node: Optional[Dict[str, Any]], paths: List[Dict[str, Any]]
) -> Dict[str, Any]:
    best = max(paths, key=lambda item: item["confidence"])
    result = _node_identity(node)
    result.update(
        {
            "role": "potentially_impacted",
            "confidence": best["confidence"],
            "confidence_label": best["confidence_label"],
            "impact_paths": sorted(
                paths, key=lambda item: item["confidence"], reverse=True
            ),
            "impact_status": _impact_status(best["confidence"]),
        }
    )
    return result


def _node_identity(node: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not node:
        return {"id": "<unknown>", "type": "UNKNOWN", "file": None}
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
        "file": node.get("file"),
        "line_start": node.get("line_start")
        or node.get("metadata", {}).get("line_start"),
        "line_end": node.get("line_end")
        or node.get("metadata", {}).get("line_end"),
    }


def _summarize_risk(
    changed_nodes: List[Dict[str, Any]],
    impacted_nodes: List[Dict[str, Any]],
    graph_quality: Dict[str, Any],
    max_depth: int,
) -> Dict[str, Any]:
    by_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    review_surfaces: List[Dict[str, Any]] = []

    for node in impacted_nodes:
        node_type = node.get("type", "UNKNOWN")
        status = node.get("impact_status", "possible")
        by_type[node_type] = by_type.get(node_type, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if node_type in BREAKAGE_NODE_TYPES:
            review_surfaces.append(
                {
                    "id": node.get("id"),
                    "type": node_type,
                    "status": status,
                    "confidence": node.get("confidence"),
                }
            )

    report_confidence = _report_confidence(changed_nodes, impacted_nodes, graph_quality)
    notes = [
        "Impacted nodes are review candidates, not guaranteed breakages.",
        f"Reverse dependency traversal was limited to {max_depth} hops.",
    ]
    notes.extend(graph_quality.get("notes", []))

    return {
        "changed_node_count": len(changed_nodes),
        "impacted_node_count": len(impacted_nodes),
        "impacted_by_type": dict(sorted(by_type.items())),
        "impacted_by_status": dict(sorted(by_status.items())),
        "review_surfaces": sorted(
            review_surfaces,
            key=lambda item: item.get("confidence", 0),
            reverse=True,
        ),
        "report_confidence": report_confidence,
        "notes": notes,
    }


def _graph_quality_diagnostics(
    graph_data: Dict[str, Any],
    seeds: Dict[str, Dict[str, Any]],
    unmatched_files: List[str],
    impacted: Set[str],
    cache: ImpactGraphCache,
) -> Dict[str, Any]:
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    unresolved_nodes = [
        node.get("id")
        for node in nodes
        if str(node.get("id", "")).startswith("unresolved:")
    ]
    low_confidence_edges = [
        edge
        for edge in edges
        if edge.get("type") in DEPENDENCY_EDGE_TYPES
        and _edge_confidence(edge) < 0.65
    ]
    seeds_without_dependents = [
        seed_id
        for seed_id in seeds
        if not [
            edge
            for edge in cache.dependents_of(seed_id)
            if edge.get("type") in DEPENDENCY_EDGE_TYPES
        ]
    ]
    dependency_edges = [
        edge for edge in edges if edge.get("type") in DEPENDENCY_EDGE_TYPES
    ]
    graph_coverage = (
        round(len(dependency_edges) / max(len(nodes), 1), 3) if nodes else 0.0
    )

    notes: List[str] = []
    if unmatched_files:
        notes.append(
            "Some changed files did not match graph nodes: " + ", ".join(unmatched_files)
        )
    if unresolved_nodes:
        notes.append(
            f"The graph contains {len(unresolved_nodes)} unresolved symbols that may hide dependencies."
        )
    if low_confidence_edges:
        notes.append(
            f"The graph contains {len(low_confidence_edges)} low-confidence dependency edges."
        )
    if seeds_without_dependents:
        notes.append(
            "Some changed nodes have no recorded reverse dependents; this may mean either low impact or missing graph edges."
        )

    score = 1.0
    score -= min(0.35, len(unmatched_files) * 0.1)
    score -= min(0.25, len(unresolved_nodes) / max(len(nodes), 1) * 0.5)
    score -= min(0.2, len(low_confidence_edges) / max(len(dependency_edges), 1) * 0.3)
    if seeds and seeds_without_dependents:
        score -= min(0.2, len(seeds_without_dependents) / len(seeds) * 0.2)

    return {
        "score": round(max(0.0, score), 3),
        "label": _confidence_label(score),
        "node_count": len(nodes),
        "dependency_edge_count": len(dependency_edges),
        "dependency_edges_per_node": graph_coverage,
        "unresolved_node_count": len(unresolved_nodes),
        "low_confidence_edge_count": len(low_confidence_edges),
        "unmatched_changed_files": unmatched_files,
        "changed_nodes_without_dependents": seeds_without_dependents,
        "impacted_node_count": len(impacted - set(seeds)),
        "notes": notes,
    }


def _overlap_evidence(
    node: Dict[str, Any], changed_lines: Set[int]
) -> Optional[Tuple[float, List[str]]]:
    start = node.get("line_start") or node.get("metadata", {}).get("line_start")
    end = node.get("line_end") or node.get("metadata", {}).get("line_end")

    if not changed_lines:
        return 0.65, ["Changed file matched node file; diff did not provide line-level evidence."]
    if start is None or end is None:
        return 0.55, ["Changed file matched, but node source span is unavailable."]
    exact = sorted(line for line in changed_lines if start <= line <= end)
    if exact:
        return 1.0, [
            f"Changed lines {exact} overlap node source span {start}-{end}."
        ]
    adjacent = sorted(line for line in changed_lines if line == end + 1)
    if adjacent:
        return 0.82, [
            f"Changed line {adjacent[0]} is adjacent to node source span {start}-{end}."
        ]
    return None


def _lookup_change(
    node_file: str, changes: Dict[str, Dict[str, Any]]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if node_file in changes:
        return node_file, changes[node_file]
    for changed_file, data in changes.items():
        if node_file.endswith(changed_file) or changed_file.endswith(node_file):
            return changed_file, data
    return None


def _normalize_path(path: str, project_path: Path) -> str:
    raw_path = Path(path)
    try:
        if raw_path.is_absolute():
            return str(raw_path.resolve().relative_to(project_path)).replace("\\", "/")
    except ValueError:
        pass
    return str(raw_path).replace("\\", "/")


def _path_evidence(edges: Iterable[Dict[str, Any]]) -> List[str]:
    evidence = []
    for edge in edges:
        detail = f"{edge.get('type')} edge"
        if edge.get("resolution"):
            detail += f" resolved as {edge.get('resolution')}"
        detail += f" with confidence {_edge_confidence(edge):.2f}"
        evidence.append(detail)
    return evidence


def _impact_status(confidence: float) -> str:
    if confidence >= 0.8:
        return "strong_candidate"
    if confidence >= 0.55:
        return "likely_candidate"
    return "possible_candidate"


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def _report_confidence(
    changed_nodes: List[Dict[str, Any]],
    impacted_nodes: List[Dict[str, Any]],
    graph_quality: Dict[str, Any],
) -> Dict[str, Any]:
    values = [node.get("confidence", 0.0) for node in changed_nodes]
    values.extend(node.get("confidence", 0.0) for node in impacted_nodes)
    evidence_score = sum(values) / len(values) if values else 0.0
    combined = round(evidence_score * graph_quality.get("score", 0.0), 3)
    return {
        "score": combined,
        "label": _confidence_label(combined),
        "evidence_score": round(evidence_score, 3),
        "graph_quality_score": graph_quality.get("score", 0.0),
    }


def _ordered_edges(edges: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        edges,
        key=lambda edge: (
            edge.get("source", ""),
            edge.get("type", ""),
            edge.get("target", ""),
        ),
    )


__all__ = ["predict_change_impact", "save_change_impact"]
