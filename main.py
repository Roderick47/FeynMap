import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any, Optional
if __package__:
    from .feyn_parser import FeynExtractor
    from .feyn_notation import FeynNotator
else:
    from feyn_parser import FeynExtractor
    from feyn_notation import FeynNotator

# Configuration Constants
MAX_JS_FUNCTIONS = 3
MAX_AJAX_CALLS = 2
DEFAULT_TRACE_DEPTH = 4
TRACE_EDGE_PRIORITY = [
    "SERIALIZER_ENTANGLEMENT",
    "CALL",
    "PARTICLE_ENTANGLEMENT",
    "EVENT",
    "AJAX",
    "DEPENDENCY",
    "VIRTUAL",
    "OBSERVATION",
]
OUTPUT_LEDGER_FILE = "feyn_ledger.json"
OUTPUT_ENHANCED_LEDGER_FILE = "feyn_ledger_enhanced.json"
OUTPUT_SEMANTIC_CLUSTERS_FILE = "feyn_semantic_clusters.json"

# Default metadata for propagators
PROPAGATOR_HTTP_METADATA = {"mass": 0.1, "energy": 1.0, "coupling": 0.9}
PROPAGATOR_AJAX_METADATA = {"mass": 0.2, "energy": 1.0, "coupling": 0.7}


class GraphCache:
    """Cache for efficient graph node and edge lookups."""
    
    def __init__(self, graph_data: Dict[str, Any]):
        """Initialize cache from graph data."""
        self.nodes: Dict[str, Dict] = {node["id"]: node for node in graph_data["nodes"]}
        self.edges: List[Dict] = graph_data["edges"]
        self._edges_by_source: Dict[str, List[Dict]] = {}
        
        # Build edge index by source node
        for edge in self.edges:
            source = edge["source"]
            if source not in self._edges_by_source:
                self._edges_by_source[source] = []
            self._edges_by_source[source].append(edge)
    
    def get_node(self, node_id: str) -> Optional[Dict]:
        """Get node by ID with O(1) lookup."""
        return self.nodes.get(node_id)
    
    def get_edges(self, source_node: str) -> List[Dict]:
        """Get all outgoing edges for a source node."""
        return self._edges_by_source.get(source_node, [])

    def get_edges_by_type(self, source_node: str, edge_type: str) -> List[str]:
        """Get target nodes for edges of a specific type from a source node."""
        edges = self.get_edges(source_node)
        return [edge["target"] for edge in edges if edge["type"] == edge_type]
    
    def get_first_edge_by_type(self, source_node: str, edge_type: str) -> Optional[str]:
        """Get the first target node for edges of a specific type."""
        targets = self.get_edges_by_type(source_node, edge_type)
        return targets[0] if targets else None


def extract_concerned_nodes(graph_data: Dict[str, Any], target_nodes: List[str]) -> Dict[str, Any]:
    """
    Smart lazy loading: Extract only concerned nodes and their dependencies.
    Builds a minimal subgraph containing only what's needed for the analysis.
    
    Args:
        graph_data: The full graph data
        target_nodes: List of node IDs to focus on
        
    Returns:
        A minimal subgraph containing target nodes and their dependencies
    """
    if not target_nodes:
        return graph_data
    
    concerned_nodes: Set[str] = set(target_nodes)
    concerned_edges: List[Dict] = []
    seen_edges: Set[Tuple[str, str, str]] = set()
    node_queue: List[str] = list(target_nodes)
    
    # Dependency discovery loop
    while node_queue:
        current_node = node_queue.pop(0)
        
        # Find all edges connected to this node
        for edge in graph_data["edges"]:
            if edge["source"] == current_node or edge["target"] == current_node:
                edge_key = (edge["source"], edge["target"], edge["type"])
                if edge_key not in seen_edges:
                    concerned_edges.append(edge)
                    seen_edges.add(edge_key)
                
                # Add connected nodes to the queue if not already processed
                connected_node = edge["target"] if edge["source"] == current_node else edge["source"]
                if connected_node not in concerned_nodes:
                    concerned_nodes.add(connected_node)
                    node_queue.append(connected_node)
    
    # Build minimal subgraph
    minimal_graph = {
        "nodes": [node for node in graph_data["nodes"] if node["id"] in concerned_nodes],
        "edges": concerned_edges
    }
    
    reduction_pct = ((1 - len(minimal_graph['nodes']) / len(graph_data['nodes'])) * 100)
    print(f"🎯 LAZY LOADING: Analyzing {len(minimal_graph['nodes'])} nodes (was {len(graph_data['nodes'])})")
    print(f"📊 Token Reduction: {reduction_pct:.1f}%")
    
    return minimal_graph


def build_metadata(metadata_map: Dict[int, Dict]) -> Dict[str, Any]:
    """
    Build physics-inspired metadata from metadata map.
    
    Args:
        metadata_map: Dictionary mapping trace indices to metadata
        
    Returns:
        Dictionary with computed metrics
    """
    return {
        "complexity": sum(meta.get("mass", 1.0) for meta in metadata_map.values()),
        "energy": sum(meta.get("energy", 0.5) for meta in metadata_map.values()),
        "coupling": max(meta.get("coupling", 0.5) for meta in metadata_map.values()) if metadata_map else 0.5
    }


def generate_node_ledger(
    node: Dict[str, Any],
    cache: GraphCache,
    interaction_type: str,
    max_depth: int = DEFAULT_TRACE_DEPTH
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate legacy and enhanced notation for a single node.
    
    Args:
        node: The node to process
        cache: Graph cache for efficient lookups
        interaction_type: "backend" or "frontend"
        max_depth: Maximum number of recursive interaction hops to trace
        
    Returns:
        Tuple of (legacy_notation, enhanced_ledger_entry)
    """
    trace: List[Tuple[str, str]] = []
    metadata_map: Dict[int, Dict] = {}
    
    if interaction_type == "backend":
        _build_backend_trace(node, cache, trace, metadata_map, max_depth)
    else:  # frontend
        _build_frontend_trace(node, cache, trace, metadata_map, max_depth)
    
    # Generate both legacy and enhanced notation
    legacy_notation = FeynNotator.generate_string(trace)
    enhanced_entry = {
        "notation": FeynNotator.generate_enhanced_string(trace, metadata_map),
        "diagram": FeynNotator.generate_diagram_data(trace, metadata_map),
        "metadata": {
            "interaction_type": interaction_type,
            "max_trace_depth": max_depth,
            "trace_length": len(trace),
            **build_metadata(metadata_map)
        }
    }
    
    return legacy_notation, enhanced_entry


def _build_backend_trace(
    node: Dict[str, Any],
    cache: GraphCache,
    trace: List[Tuple[str, str]],
    metadata_map: Dict[int, Dict],
    max_depth: int = DEFAULT_TRACE_DEPTH
) -> None:
    """Build recursive interaction trace for backend (VERTEX) nodes."""
    trace.append(("PROPAGATOR_HTTP", "URL"))
    metadata_map[0] = PROPAGATOR_HTTP_METADATA

    _append_node_trace(node["id"], node.get("type", "VERTEX"), cache, trace, metadata_map)
    _trace_interaction_chain(node["id"], cache, trace, metadata_map, max_depth, {node["id"]})


def _build_frontend_trace(
    node: Dict[str, Any],
    cache: GraphCache,
    trace: List[Tuple[str, str]],
    metadata_map: Dict[int, Dict],
    max_depth: int = DEFAULT_TRACE_DEPTH
) -> None:
    """Build recursive interaction trace for frontend nodes."""
    _append_node_trace(node["id"], node.get("type", "FRONTEND"), cache, trace, metadata_map)
    _trace_interaction_chain(node["id"], cache, trace, metadata_map, max_depth, {node["id"]})


def _trace_interaction_chain(
    source_node: str,
    cache: GraphCache,
    trace: List[Tuple[str, str]],
    metadata_map: Dict[int, Dict],
    remaining_depth: int,
    visited: Set[str]
) -> None:
    """Recursively append reachable interactions from a source node."""
    if remaining_depth <= 0:
        return

    for edge in _ordered_trace_edges(cache.get_edges(source_node)):
        target = edge.get("target")
        if not target or target in visited:
            continue

        target_node = cache.get_node(target)
        role = _role_for_edge(edge.get("type", ""), target_node)
        _append_node_trace(target, role, cache, trace, metadata_map)

        if target_node and target_node.get("type") not in {"PARTICLE", "TRANSFORM", "AJAX", "DEPENDENCY"}:
            _trace_interaction_chain(target, cache, trace, metadata_map, remaining_depth - 1, visited | {target})


def _ordered_trace_edges(edges: List[Dict]) -> List[Dict]:
    """Return edges in a stable order that keeps canonical relationships readable."""
    priority = {edge_type: index for index, edge_type in enumerate(TRACE_EDGE_PRIORITY)}
    return sorted(edges, key=lambda edge: (priority.get(edge.get("type"), len(priority)), edge.get("target", "")))


def _role_for_edge(edge_type: str, target_node: Optional[Dict]) -> str:
    """Map graph edge and node metadata into Feynman notation roles."""
    if edge_type == "SERIALIZER_ENTANGLEMENT":
        return "TRANSFORM"
    if edge_type == "PARTICLE_ENTANGLEMENT":
        return "PARTICLE"
    if edge_type == "AJAX":
        return "PROPAGATOR_AJAX"
    if target_node:
        return target_node.get("type", "MEDIATOR")
    return "MEDIATOR"


def _append_node_trace(
    node_id: str,
    role: str,
    cache: GraphCache,
    trace: List[Tuple[str, str]],
    metadata_map: Dict[int, Dict]
) -> None:
    """Append a node to the trace with its metadata."""
    trace.append((role, node_id))
    node = cache.get_node(node_id)
    metadata_map[len(trace) - 1] = node.get("metadata", {}) if node else {}


def detect_unused_nodes(enhanced_ledger: Dict[str, Any], graph_data: Dict[str, Any]) -> Set[str]:
    """
    Detect unused nodes (dead code) in the graph.
    
    Args:
        enhanced_ledger: The enhanced ledger with trace information
        graph_data: The full graph data
        
    Returns:
        Set of unused node IDs
    """
    all_node_ids = {node['id'] for node in graph_data['nodes']}
    used_node_ids: Set[str] = set()
    
    # Collect all nodes referenced in traces
    for node_id, entry in enhanced_ledger.items():
        used_node_ids.add(node_id)
        # Extract graph node names from structured diagram data if available.
        for category in entry.get("diagram", {}).values():
            for item in category:
                if isinstance(item, dict) and "name" in item:
                    used_node_ids.add(item["name"])
    
    return all_node_ids - used_node_ids


SEMANTIC_NODE_TYPES = {"VERTEX", "TRANSFORM", "PARTICLE", "MEDIATOR", "FRONTEND"}
CRUD_INTENT_ALIASES = {
    "create": {"create", "new", "add", "post", "insert"},
    "read": {"read", "retrieve", "detail", "show", "get", "list", "index", "all", "search"},
    "update": {"update", "edit", "patch", "put", "modify"},
    "delete": {"delete", "destroy", "remove"},
}
SEMANTIC_SUFFIXES = {
    "view", "views", "apiview", "controller", "serializer", "schema", "model",
    "service", "helper", "manager", "handler", "endpoint", "api", "form", "resource",
}


def generate_semantic_clusters(graph_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Group nodes by inferred semantic role, touched data subjects, and behavior.

    The graph keeps physical dependencies exact; semantic clusters add mental
    categories for AI agents and new developers by grouping nodes that look like
    they serve the same product function even when no explicit edge connects them.
    """
    cache = GraphCache(graph_data)
    profiles = {
        node["id"]: _build_semantic_profile(node, cache)
        for node in graph_data.get("nodes", [])
        if node.get("type") in SEMANTIC_NODE_TYPES
    }

    clusters_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for node_id, profile in profiles.items():
        for key in _semantic_cluster_keys(profile):
            cluster = clusters_by_key.setdefault(key, _new_semantic_cluster(key))
            cluster["members"].append(node_id)
            cluster["member_profiles"][node_id] = {
                "type": profile["type"],
                "intent": profile["intent"],
                "data_subjects": sorted(profile["data_subjects"]),
                "tokens": sorted(profile["tokens"]),
                "evidence": profile["evidence"],
            }
            cluster["data_subjects"].update(profile["data_subjects"])
            cluster["intents"].add(profile["intent"])
            cluster["node_types"].add(profile["type"])

    clusters = []
    node_memberships: Dict[str, List[str]] = {node_id: [] for node_id in profiles}
    cluster_index = 1
    for cluster in clusters_by_key.values():
        if len(cluster["members"]) < 2:
            continue

        cluster_id = f"semantic_cluster_{cluster_index:03d}"
        cluster_index += 1
        cluster["id"] = cluster_id
        cluster["members"] = sorted(cluster["members"])
        cluster["data_subjects"] = sorted(cluster["data_subjects"])
        cluster["intents"] = sorted(cluster["intents"])
        cluster["node_types"] = sorted(cluster["node_types"])
        cluster["confidence"] = _calculate_cluster_confidence(cluster)
        cluster["summary"] = _summarize_semantic_cluster(cluster)
        clusters.append(cluster)

        for member in cluster["members"]:
            node_memberships.setdefault(member, []).append(cluster_id)

    serializable_profiles = {
        node_id: {
            **profile,
            "tokens": sorted(profile.get("tokens", set())),
            "data_subjects": sorted(profile.get("data_subjects", set())),
            "edge_types": sorted(profile.get("edge_types", set())),
        }
        for node_id, profile in profiles.items()
    }

    return {
        "clusters": clusters,
        "node_memberships": {node: ids for node, ids in node_memberships.items() if ids},
        "profiles": serializable_profiles,
        "metadata": {
            "cluster_count": len(clusters),
            "profiled_node_count": len(profiles),
            "purpose": "Group semantically similar nodes so FeynMap can present mental categories alongside exact graph traces.",
        },
    }


def annotate_ledger_with_semantic_clusters(
    enhanced_ledger: Dict[str, Dict[str, Any]],
    semantic_clusters: Dict[str, Any]
) -> None:
    """Attach semantic cluster memberships to enhanced ledger entries in-place."""
    memberships = semantic_clusters.get("node_memberships", {})
    clusters_by_id = {cluster["id"]: cluster for cluster in semantic_clusters.get("clusters", [])}

    for node_id, entry in enhanced_ledger.items():
        cluster_ids = memberships.get(node_id, [])
        if not cluster_ids:
            continue

        entry["semantic_clusters"] = [
            {
                "id": cluster_id,
                "summary": clusters_by_id[cluster_id]["summary"],
                "confidence": clusters_by_id[cluster_id]["confidence"],
                "members": clusters_by_id[cluster_id]["members"],
            }
            for cluster_id in cluster_ids
            if cluster_id in clusters_by_id
        ]
        entry.setdefault("metadata", {})["semantic_cluster_count"] = len(entry["semantic_clusters"])


def _new_semantic_cluster(key: Tuple[str, str]) -> Dict[str, Any]:
    """Create a semantic cluster accumulator."""
    scope, role = key
    return {
        "scope": scope,
        "role": role,
        "members": [],
        "member_profiles": {},
        "data_subjects": set(),
        "intents": set(),
        "node_types": set(),
    }


def _build_semantic_profile(node: Dict[str, Any], cache: GraphCache) -> Dict[str, Any]:
    """Infer data subjects and functional intent for one graph node."""
    node_id = node["id"]
    node_type = node.get("type", "UNKNOWN")
    tokens = _semantic_tokens(node_id)
    outgoing_edges = cache.get_edges(node_id)
    data_subjects = _infer_data_subjects(node, tokens, outgoing_edges)
    intent = _infer_intent(node_id, node_type, tokens)
    role = _semantic_role(node_type, intent, bool(data_subjects))

    evidence = []
    if data_subjects:
        evidence.append(f"data_subjects={','.join(sorted(data_subjects))}")
    if intent != "generic":
        evidence.append(f"intent={intent}")
    if outgoing_edges:
        evidence.append("edges=" + ",".join(sorted({edge.get("type", "") for edge in outgoing_edges})))

    return {
        "id": node_id,
        "type": node_type,
        "role": role,
        "intent": intent,
        "tokens": tokens,
        "data_subjects": data_subjects,
        "edge_types": {edge.get("type", "") for edge in outgoing_edges},
        "evidence": evidence,
    }


def _semantic_cluster_keys(profile: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Return cluster keys for a profile, preferring data-centric groupings."""
    keys: List[Tuple[str, str]] = []
    subjects = profile.get("data_subjects", set())
    role = profile.get("role", "generic")

    for subject in subjects:
        keys.append((f"data:{subject}", role))
        if role == "crud_interface":
            keys.append((f"data:{subject}", "data_workflow"))

    if not keys:
        signature_tokens = sorted(profile.get("tokens", set()))[:2]
        if signature_tokens:
            keys.append((f"tokens:{'-'.join(signature_tokens)}", role))

    return keys


def _semantic_tokens(node_id: str) -> Set[str]:
    """Split node identifiers into lowercase semantic tokens."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", node_id)
    raw_tokens = re.split(r"[^A-Za-z0-9]+", spaced)
    return {
        token.lower()
        for token in raw_tokens
        if token and token.lower() not in SEMANTIC_SUFFIXES
    }


def _infer_data_subjects(node: Dict[str, Any], tokens: Set[str], edges: List[Dict]) -> Set[str]:
    """Infer domain/data subjects from explicit graph edges and naming conventions."""
    subjects = {
        _normalize_subject(edge["target"])
        for edge in edges
        if edge.get("type") == "PARTICLE_ENTANGLEMENT" and edge.get("target")
    }

    node_type = node.get("type")
    if node_type == "PARTICLE":
        subjects.add(_normalize_subject(node["id"]))
    elif node_type == "TRANSFORM" and not subjects:
        subjects.add(_normalize_subject(_strip_suffixes(node["id"], ["Serializer", "Schema"])))
    elif not subjects:
        name_without_suffix = _strip_suffixes(
            node["id"],
            ["CreateView", "UpdateView", "DeleteView", "DetailView", "ListView", "View", "Controller"]
        )
        if name_without_suffix != node["id"] and name_without_suffix:
            subjects.add(_normalize_subject(name_without_suffix))

    return {subject for subject in subjects if subject and subject.lower() not in CRUD_INTENT_ALIASES}


def _infer_intent(node_id: str, node_type: str, tokens: Set[str]) -> str:
    """Classify a node's behavior into CRUD/data transformation categories."""
    for intent, aliases in CRUD_INTENT_ALIASES.items():
        if tokens & aliases:
            return intent

    lowered = node_id.lower()
    for intent, aliases in CRUD_INTENT_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return intent

    if node_type == "TRANSFORM":
        return "transform"
    if node_type == "PARTICLE":
        return "data_model"
    if node_type == "FRONTEND":
        return "interface"
    return "generic"


def _semantic_role(node_type: str, intent: str, has_subject: bool) -> str:
    """Map graph node type and intent into a human-scale semantic category."""
    if node_type == "VERTEX" and (has_subject or intent in {"create", "read", "update", "delete"}):
        return "crud_interface"
    if node_type == "TRANSFORM":
        return "data_transform"
    if node_type == "PARTICLE":
        return "data_model"
    if node_type == "MEDIATOR" and has_subject:
        return "data_service"
    if node_type == "FRONTEND":
        return "frontend_surface"
    return "supporting_logic"


def _strip_suffixes(value: str, suffixes: List[str]) -> str:
    """Remove the first matching semantic suffix from an identifier."""
    for suffix in suffixes:
        if value.endswith(suffix):
            return value[:-len(suffix)]
    return value


def _normalize_subject(value: str) -> str:
    """Normalize a subject while preserving a readable model-style name."""
    cleaned = _strip_suffixes(value, ["Serializer", "Schema", "Model"])
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", cleaned).strip()
    if not cleaned:
        return ""
    return "".join(part.capitalize() for part in cleaned.split())


def _calculate_cluster_confidence(cluster: Dict[str, Any]) -> float:
    """Score confidence based on shared subjects, roles, and semantic evidence."""
    confidence = 0.5
    if cluster.get("data_subjects"):
        confidence += 0.25
    if len(cluster.get("node_types", [])) == 1 or len(cluster.get("intents", [])) <= 2:
        confidence += 0.15
    if any(profile.get("evidence") for profile in cluster.get("member_profiles", {}).values()):
        confidence += 0.1
    return round(min(confidence, 0.95), 2)


def _summarize_semantic_cluster(cluster: Dict[str, Any]) -> str:
    """Create a concise explanation of why members are grouped."""
    subjects = cluster.get("data_subjects", [])
    subject_text = ", ".join(subjects) if subjects else cluster.get("scope", "shared tokens")
    role = cluster.get("role", "related logic").replace("_", " ")
    intents = cluster.get("intents", [])
    intent_text = f" ({', '.join(intents)})" if intents else ""
    return f"{role.title()} around {subject_text}{intent_text}"


def save_outputs(
    ledger: Dict[str, Any],
    enhanced_ledger: Dict[str, Any],
    semantic_clusters: Optional[Dict[str, Any]] = None
) -> None:
    """
    Save ledger outputs to JSON files.
    
    Args:
        ledger: Legacy notation ledger
        enhanced_ledger: Enhanced notation ledger
        semantic_clusters: Optional semantic similarity cluster report
    """
    with open(OUTPUT_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=4)
    
    with open(OUTPUT_ENHANCED_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(enhanced_ledger, f, indent=4)

    if semantic_clusters is not None:
        with open(OUTPUT_SEMANTIC_CLUSTERS_FILE, "w", encoding="utf-8") as f:
            json.dump(semantic_clusters, f, indent=4)


def run_feynmap(
    project_dir: str,
    target_nodes: Optional[List[str]] = None,
    lazy_load: bool = True,
    framework: str = 'auto',
    trace_depth: int = DEFAULT_TRACE_DEPTH
) -> None:
    """
    Run FeynMap analysis on a project directory.
    
    Args:
        project_dir: Path to the project directory to analyze
        target_nodes: Optional list of specific nodes to analyze
        lazy_load: Whether to use lazy loading for efficiency
        framework: Framework to use for pattern detection
        trace_depth: Maximum number of recursive interaction hops to trace
        
    Raises:
        FileNotFoundError: If project_dir does not exist
    """
    # Validate project directory
    project_path = Path(project_dir)
    if not project_path.exists():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")
    
    # Setup & Extraction
    extractor = FeynExtractor(project_dir, framework=framework)
    graph_data = extractor.scan()
    
    # Smart Lazy Loading
    if lazy_load and target_nodes:
        graph_data = extract_concerned_nodes(graph_data, target_nodes)
    
    # Initialize graph cache for efficient lookups
    cache = GraphCache(graph_data)
    
    # Generate the Enhanced Ledger
    ledger: Dict[str, str] = {}
    enhanced_ledger: Dict[str, Dict[str, Any]] = {}
    
    for node in graph_data["nodes"]:
        node_type = node.get("type")
        
        if node_type == "VERTEX":
            legacy, enhanced = generate_node_ledger(node, cache, "backend", trace_depth)
            ledger[node["id"]] = legacy
            enhanced_ledger[node["id"]] = enhanced
        
        elif node_type == "FRONTEND":
            legacy, enhanced = generate_node_ledger(node, cache, "frontend", trace_depth)
            ledger[node["id"]] = legacy
            enhanced_ledger[node["id"]] = enhanced
    
    # Build semantic similarity clusters before ghost detection so ledger entries
    # carry both exact traces and mental categories.
    semantic_clusters = generate_semantic_clusters(graph_data)
    annotate_ledger_with_semantic_clusters(enhanced_ledger, semantic_clusters)

    # Detect unused nodes (dead code)
    ghost_states = detect_unused_nodes(enhanced_ledger, graph_data)
    
    # Save Outputs
    save_outputs(ledger, enhanced_ledger, semantic_clusters)
    
    # Report Results
    print("=" * 50)
    print(f" FEYNMAP V2 - ENHANCED PHYSICS NOTATION ({framework.upper()}) ")
    print("=" * 50)
    
    if ghost_states:
        print(f"\n[!] UNUSED NODES DETECTED ({len(ghost_states)}):")
        for ghost in sorted(ghost_states):
            print(f"  - {ghost}")
    else:
        print("\n[✓] NO UNUSED NODES: Every node is active in the Standard Model.")
    
    print(f"\n[SUCCESS] Enhanced Ledger and Graph updated.")
    print(f"[INFO] Enhanced notation saved to '{OUTPUT_ENHANCED_LEDGER_FILE}'")
    print(f"[INFO] Semantic clusters saved to '{OUTPUT_SEMANTIC_CLUSTERS_FILE}'")
    print(f"[INFO] Semantic clusters: {semantic_clusters['metadata']['cluster_count']}")
    print(f"[INFO] Framework: {framework}")
    print(f"[INFO] Trace depth: {trace_depth}")
    print(f"[INFO] Analyzed {len(graph_data['nodes'])} nodes and {len(graph_data['edges'])} edges")


if __name__ == "__main__":
    import argparse

    sys.stdout.reconfigure(encoding="utf-8")
    
    parser = argparse.ArgumentParser(description='FeynMap - Code Analysis with Physics-Inspired Notation')
    parser.add_argument('path', nargs='?', default='.', help='Project directory to analyze')
    parser.add_argument('--target-nodes', '-t', help='Comma-separated list of target nodes for lazy loading')
    parser.add_argument('--no-lazy-load', action='store_true', help='Disable lazy loading')
    parser.add_argument('--framework', '-f', default='auto', 
                       choices=['auto', 'django', 'flask', 'fastapi', 'rails', 'generic'],
                       help='Framework to use for pattern detection (default: auto)')
    parser.add_argument('--trace-depth', type=int, default=DEFAULT_TRACE_DEPTH,
                       help=f'Maximum recursive interaction hops to trace (default: {DEFAULT_TRACE_DEPTH})')
    
    args = parser.parse_args()
    
    # Parse target nodes
    target_nodes = None
    if args.target_nodes:
        target_nodes = [node.strip() for node in args.target_nodes.split(',')]
    
    lazy_load = not args.no_lazy_load
    
    run_feynmap(args.path, target_nodes, lazy_load, args.framework, args.trace_depth)
