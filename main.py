import json
import sys
import io
import re
try:
    from .feyn_parser import FeynExtractor
    from .feyn_notation import FeynNotator
except ImportError:
    from feyn_parser import FeynExtractor
    from feyn_notation import FeynNotator

def extract_concerned_nodes(graph_data, target_nodes):
    """
    Smart lazy loading: Extract only concerned nodes and their dependencies.
    Builds a minimal subgraph containing only what's needed for the analysis.
    """
    if not target_nodes:
        return graph_data
    
    concerned_nodes = set(target_nodes)
    concerned_edges = []
    node_queue = list(target_nodes)
    
    # Dependency discovery loop
    while node_queue:
        current_node = node_queue.pop(0)
        
        # Find all edges connected to this node
        for edge in graph_data["edges"]:
            if edge["source"] == current_node or edge["target"] == current_node:
                concerned_edges.append(edge)
                
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
    
    print(f"🎯 LAZY LOADING: Analyzing {len(minimal_graph['nodes'])} nodes (was {len(graph_data['nodes'])})")
    print(f"📊 Token Reduction: {((1 - len(minimal_graph['nodes']) / len(graph_data['nodes'])) * 100):.1f}%")
    
    return minimal_graph

def run_feynmap(project_dir, target_nodes=None, lazy_load=True, framework='auto'):
    # 1. Setup & Extraction
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    extractor = FeynExtractor(project_dir, framework=framework)
    graph_data = extractor.scan()

    # 2. Smart Lazy Loading - Only process concerned nodes and their dependencies
    if lazy_load and target_nodes:
        graph_data = extract_concerned_nodes(graph_data, target_nodes)
    
    # 3. Generate the Enhanced Ledger with Physics-Inspired Notation
    ledger = {}
    enhanced_ledger = {}
    
    for node in graph_data["nodes"]:
        if node["type"] == "VERTEX":
            # Build the interaction trace for backend views with physics symbols
            trace = []
            metadata_map = {}
            
            # Use appropriate propagator type
            propagator_type = "PROPAGATOR_HTTP"  # Standard HTTP requests
            trace.append((propagator_type, "URL"))
            metadata_map[0] = {"mass": 0.1, "energy": 1.0, "coupling": 0.9}
            
            trace.append(("VERTEX", node["id"]))
            metadata_map[1] = node.get("metadata", {})
            
            # Look for Serializer Entanglement edges first
            for edge in graph_data["edges"]:
                if edge["type"] == "SERIALIZER_ENTANGLEMENT" and edge["source"] == node["id"]:
                    trace.append(("TRANSFORM", edge["target"]))
                    # Find the serializer node to get its metadata
                    serializer_node = next((n for n in graph_data["nodes"] if n["id"] == edge["target"]), None)
                    metadata_map[len(trace)-1] = serializer_node.get("metadata", {}) if serializer_node else {}
                    break
            
            # Look for Particle Entanglement edges
            for edge in graph_data["edges"]:
                if edge["type"] == "PARTICLE_ENTANGLEMENT" and edge["source"] == node["id"]:
                    trace.append(("PARTICLE", edge["target"]))
                    # Find the model node to get its metadata
                    model_node = next((n for n in graph_data["nodes"] if n["id"] == edge["target"]), None)
                    metadata_map[len(trace)-1] = model_node.get("metadata", {}) if model_node else {}
                    break
            
            # Generate both legacy and enhanced notation
            ledger[node["id"]] = FeynNotator.generate_string(trace)
            enhanced_ledger[node["id"]] = {
                "notation": FeynNotator.generate_enhanced_string(trace, metadata_map),
                "diagram": FeynNotator.generate_diagram_data(trace, metadata_map),
                "metadata": {
                    "interaction_type": "backend",
                    "complexity": sum(meta.get("mass", 1.0) for meta in metadata_map.values()),
                    "energy": sum(meta.get("energy", 0.5) for meta in metadata_map.values()),
                    "coupling": max(meta.get("coupling", 0.5) for meta in metadata_map.values())
                }
            }
        
        elif node["type"] == "FRONTEND":
            # Build the interaction trace for frontend templates with physics symbols
            trace = []
            metadata_map = {}
            
            trace.append(("FRONTEND", node["id"]))
            metadata_map[0] = node.get("metadata", {})
            
            # Find connected components
            js_functions = [edge["target"] for edge in graph_data["edges"] 
                           if edge["source"] == node["id"] and edge["type"] == "EVENT"]
            ajax_calls = [edge["target"] for edge in graph_data["edges"] 
                        if edge["source"] == node["id"] and edge["type"] == "AJAX"]
            dependencies = [edge["target"] for edge in graph_data["edges"] 
                           if edge["source"] == node["id"] and edge["type"] == "DEPENDENCY"]
            virtual_funcs = [edge["target"] for edge in graph_data["edges"] 
                           if edge["source"] == node["id"] and edge["type"] == "VIRTUAL"]
            
            # Add JavaScript functions to trace
            for func in js_functions[:3]:
                trace.append(("JAVASCRIPT", func))
                js_node = next((n for n in graph_data["nodes"] if n["id"] == func), None)
                metadata_map[len(trace)-1] = js_node.get("metadata", {}) if js_node else {}
            
            # Add AJAX calls to trace (use electromagnetic propagator)
            for ajax in ajax_calls[:2]:
                trace.append(("PROPAGATOR_AJAX", ajax))
                metadata_map[len(trace)-1] = {"mass": 0.2, "energy": 1.0, "coupling": 0.7}
            
            # Add dependencies to trace
            for dep in dependencies:
                trace.append(("DEPENDENCY", dep))
                dep_node = next((n for n in graph_data["nodes"] if n["id"] == dep), None)
                metadata_map[len(trace)-1] = dep_node.get("metadata", {}) if dep_node else {}
            
            # Add virtual functions to trace
            for virt in virtual_funcs:
                trace.append(("VIRTUAL", virt))
                virt_node = next((n for n in graph_data["nodes"] if n["id"] == virt), None)
                metadata_map[len(trace)-1] = virt_node.get("metadata", {}) if virt_node else {}
            
            # Generate both legacy and enhanced notation
            ledger[node["id"]] = FeynNotator.generate_string(trace)
            enhanced_ledger[node["id"]] = {
                "notation": FeynNotator.generate_enhanced_string(trace, metadata_map),
                "diagram": FeynNotator.generate_diagram_data(trace, metadata_map),
                "metadata": {
                    "interaction_type": "frontend",
                    "complexity": sum(meta.get("mass", 1.0) for meta in metadata_map.values()),
                    "energy": sum(meta.get("energy", 0.5) for meta in metadata_map.values()),
                    "coupling": max(meta.get("coupling", 0.5) for meta in metadata_map.values())
                }
            }
    
    # 3. THE VACUUM: Ghost State (Dead Code) Detection
    all_node_ids = {node['id'] for node in graph_data['nodes']}
    used_node_ids = set()
    
    for path_string in ledger.values():
        nodes_in_path = re.findall(r'\[(.*?)\]', path_string)
        used_node_ids.update(nodes_in_path)

    ghost_states = all_node_ids - used_node_ids

    # 4. Save Outputs (both legacy and enhanced)
    with open("feyn_ledger.json", "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=4)
    
    with open("feyn_ledger_enhanced.json", "w", encoding="utf-8") as f:
        json.dump(enhanced_ledger, f, indent=4)

    # 5. Report Anomalies to the Console
    print("="*50)
    print(f" FEYNMAP V2 - ENHANCED PHYSICS NOTATION ({framework.upper()}) ")
    print("="*50)
    
    if ghost_states:
        print(f"\n[!] GHOST STATES DETECTED ({len(ghost_states)}):")
        for ghost in ghost_states:
            print(f"  - {ghost}")
    else:
        print("\n[✓] NO GHOST STATES: Every node is active in the Standard Model.")

    print(f"\n[SUCCESS] Enhanced Ledger and Graph updated.")
    print(f"[INFO] Enhanced notation saved to 'feyn_ledger_enhanced.json'")
    print(f"[INFO] Framework: {framework}")
    print(f"[INFO] Analyzed {len(graph_data['nodes'])} nodes and {len(graph_data['edges'])} edges")

if __name__ == "__main__":
    import argparse
    
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
