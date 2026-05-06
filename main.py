import json
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
OUTPUT_LEDGER_FILE = "feyn_ledger.json"
OUTPUT_ENHANCED_LEDGER_FILE = "feyn_ledger_enhanced.json"

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
    
    def get_edges_by_type(self, source_node: str, edge_type: str) -> List[str]:
        """Get target nodes for edges of a specific type from a source node."""
        edges = self._edges_by_source.get(source_node, [])
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
    interaction_type: str
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate legacy and enhanced notation for a single node.
    
    Args:
        node: The node to process
        cache: Graph cache for efficient lookups
        interaction_type: "backend" or "frontend"
        
    Returns:
        Tuple of (legacy_notation, enhanced_ledger_entry)
    """
    trace: List[Tuple[str, str]] = []
    metadata_map: Dict[int, Dict] = {}
    
    if interaction_type == "backend":
        _build_backend_trace(node, cache, trace, metadata_map)
    else:  # frontend
        _build_frontend_trace(node, cache, trace, metadata_map)
    
    # Generate both legacy and enhanced notation
    legacy_notation = FeynNotator.generate_string(trace)
    enhanced_entry = {
        "notation": FeynNotator.generate_enhanced_string(trace, metadata_map),
        "diagram": FeynNotator.generate_diagram_data(trace, metadata_map),
        "metadata": {
            "interaction_type": interaction_type,
            **build_metadata(metadata_map)
        }
    }
    
    return legacy_notation, enhanced_entry


def _build_backend_trace(
    node: Dict[str, Any],
    cache: GraphCache,
    trace: List[Tuple[str, str]],
    metadata_map: Dict[int, Dict]
) -> None:
    """Build interaction trace for backend (VERTEX) nodes."""
    # HTTP request propagator
    trace.append(("PROPAGATOR_HTTP", "URL"))
    metadata_map[0] = PROPAGATOR_HTTP_METADATA
    
    # Vertex node
    trace.append(("VERTEX", node["id"]))
    metadata_map[1] = node.get("metadata", {})
    
    # Serializer Entanglement
    serializer_target = cache.get_first_edge_by_type(node["id"], "SERIALIZER_ENTANGLEMENT")
    if serializer_target:
        trace.append(("TRANSFORM", serializer_target))
        serializer_node = cache.get_node(serializer_target)
        metadata_map[len(trace) - 1] = serializer_node.get("metadata", {}) if serializer_node else {}
    
    # Particle Entanglement
    particle_target = cache.get_first_edge_by_type(node["id"], "PARTICLE_ENTANGLEMENT")
    if particle_target:
        trace.append(("PARTICLE", particle_target))
        model_node = cache.get_node(particle_target)
        metadata_map[len(trace) - 1] = model_node.get("metadata", {}) if model_node else {}


def _build_frontend_trace(
    node: Dict[str, Any],
    cache: GraphCache,
    trace: List[Tuple[str, str]],
    metadata_map: Dict[int, Dict]
) -> None:
    """Build interaction trace for frontend nodes."""
    # Frontend node
    trace.append(("FRONTEND", node["id"]))
    metadata_map[0] = node.get("metadata", {})
    
    # JavaScript functions
    js_functions = cache.get_edges_by_type(node["id"], "EVENT")
    for func in js_functions[:MAX_JS_FUNCTIONS]:
        trace.append(("JAVASCRIPT", func))
        js_node = cache.get_node(func)
        metadata_map[len(trace) - 1] = js_node.get("metadata", {}) if js_node else {}
    
    # AJAX calls
    ajax_calls = cache.get_edges_by_type(node["id"], "AJAX")
    for ajax in ajax_calls[:MAX_AJAX_CALLS]:
        trace.append(("PROPAGATOR_AJAX", ajax))
        metadata_map[len(trace) - 1] = PROPAGATOR_AJAX_METADATA
    
    # Dependencies
    dependencies = cache.get_edges_by_type(node["id"], "DEPENDENCY")
    for dep in dependencies:
        trace.append(("DEPENDENCY", dep))
        dep_node = cache.get_node(dep)
        metadata_map[len(trace) - 1] = dep_node.get("metadata", {}) if dep_node else {}
    
    # Virtual functions
    virtual_funcs = cache.get_edges_by_type(node["id"], "VIRTUAL")
    for virt in virtual_funcs:
        trace.append(("VIRTUAL", virt))
        virt_node = cache.get_node(virt)
        metadata_map[len(trace) - 1] = virt_node.get("metadata", {}) if virt_node else {}


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


def save_outputs(ledger: Dict[str, Any], enhanced_ledger: Dict[str, Any]) -> None:
    """
    Save ledger outputs to JSON files.
    
    Args:
        ledger: Legacy notation ledger
        enhanced_ledger: Enhanced notation ledger
    """
    with open(OUTPUT_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=4)
    
    with open(OUTPUT_ENHANCED_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(enhanced_ledger, f, indent=4)


def run_feynmap(
    project_dir: str,
    target_nodes: Optional[List[str]] = None,
    lazy_load: bool = True,
    framework: str = 'auto'
) -> None:
    """
    Run FeynMap analysis on a project directory.
    
    Args:
        project_dir: Path to the project directory to analyze
        target_nodes: Optional list of specific nodes to analyze
        lazy_load: Whether to use lazy loading for efficiency
        framework: Framework to use for pattern detection
        
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
            legacy, enhanced = generate_node_ledger(node, cache, "backend")
            ledger[node["id"]] = legacy
            enhanced_ledger[node["id"]] = enhanced
        
        elif node_type == "FRONTEND":
            legacy, enhanced = generate_node_ledger(node, cache, "frontend")
            ledger[node["id"]] = legacy
            enhanced_ledger[node["id"]] = enhanced
    
    # Detect unused nodes (dead code)
    ghost_states = detect_unused_nodes(enhanced_ledger, graph_data)
    
    # Save Outputs
    save_outputs(ledger, enhanced_ledger)
    
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
    print(f"[INFO] Framework: {framework}")
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
    
    args = parser.parse_args()
    
    # Parse target nodes
    target_nodes = None
    if args.target_nodes:
        target_nodes = [node.strip() for node in args.target_nodes.split(',')]
    
    lazy_load = not args.no_lazy_load
    
    run_feynmap(args.path, target_nodes, lazy_load, args.framework)
