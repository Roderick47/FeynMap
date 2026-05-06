import json
import sys
from typing import Any, Dict, Set

if __package__:
    from .feyn_parser import FeynExtractor
    from .feyn_notation import FeynNotator
else:
    from feyn_parser import FeynExtractor
    from feyn_notation import FeynNotator


def detect_unused_nodes(enhanced_ledger: Dict[str, Any], graph_data: Dict[str, Any]) -> Set[str]:
    """Detect graph nodes that were not referenced by structured diagram data."""
    all_node_ids = {node["id"] for node in graph_data["nodes"]}
    used_node_ids: Set[str] = set()

    for node_id, entry in enhanced_ledger.items():
        used_node_ids.add(node_id)
        for category in entry.get("diagram", {}).values():
            for item in category:
                if isinstance(item, dict) and "name" in item:
                    used_node_ids.add(item["name"])

    return all_node_ids - used_node_ids


def run_feynmap(project_dir):
    # 1. Setup & Extraction
    extractor = FeynExtractor(project_dir)
    graph_data = extractor.scan()

    # 2. Generate the Ledger (Interaction Paths) using FeynNotator
    ledger = {}
    enhanced_ledger = {}
    
    for node in graph_data["nodes"]:
        if node["type"] == "VERTEX":
            # Build the interaction trace for backend views
            trace = []
            trace.append(("PROPAGATOR", "URL"))
            trace.append(("VERTEX", node["id"]))
            
            # Look for Serializer Entanglement edges first
            for edge in graph_data["edges"]:
                if edge["type"] == "SERIALIZER_ENTANGLEMENT" and edge["source"] == node["id"]:
                    trace.append(("TRANSFORM", edge["target"]))
                    break
            
            # Look for Particle Entanglement edges
            for edge in graph_data["edges"]:
                if edge["type"] == "PARTICLE_ENTANGLEMENT" and edge["source"] == node["id"]:
                    trace.append(("PARTICLE", edge["target"]))
                    break  # For now, assume one model per view
            
            ledger[node["id"]] = FeynNotator.generate_string(trace)
            enhanced_ledger[node["id"]] = {
                "notation": FeynNotator.generate_enhanced_string(trace),
                "diagram": FeynNotator.generate_diagram_data(trace),
            }
        
        elif node["type"] == "FRONTEND":
            # Build the interaction trace for frontend templates
            trace = []
            trace.append(("FRONTEND", node["id"]))
            
            # Find connected JavaScript functions
            js_functions = [edge["target"] for edge in graph_data["edges"] 
                           if edge["source"] == node["id"] and edge["type"] == "EVENT"]
            
            # Find AJAX calls
            ajax_calls = [edge["target"] for edge in graph_data["edges"] 
                        if edge["source"] == node["id"] and edge["type"] == "AJAX"]
            
            # Find dependencies
            dependencies = [edge["target"] for edge in graph_data["edges"] 
                           if edge["source"] == node["id"] and edge["type"] == "DEPENDENCY"]
            
            # Find virtual/async functions
            virtual_funcs = [edge["target"] for edge in graph_data["edges"] 
                           if edge["source"] == node["id"] and edge["type"] == "VIRTUAL"]
            
            # Add JavaScript functions to trace
            for func in js_functions[:3]:  # Limit to first 3
                trace.append(("JAVASCRIPT", func))
            
            # Add AJAX calls to trace
            for ajax in ajax_calls[:2]:  # Limit to first 2
                trace.append(("AJAX", ajax))
            
            # Add dependencies to trace
            for dep in dependencies:
                trace.append(("DEPENDENCY", dep))
            
            # Add virtual functions to trace
            for virt in virtual_funcs:
                trace.append(("VIRTUAL", virt))
            
            ledger[node["id"]] = FeynNotator.generate_string(trace)
            enhanced_ledger[node["id"]] = {
                "notation": FeynNotator.generate_enhanced_string(trace),
                "diagram": FeynNotator.generate_diagram_data(trace),
            }

    # 3. THE VACUUM: Ghost State (Dead Code) Detection
    # Ghost States = Objects defined but never utilized in a flow
    ghost_states = detect_unused_nodes(enhanced_ledger, graph_data)

    # 4. Save Outputs
    with open("feyn_ledger.json", "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=4)

    # 5. Report Anomalies to the Console
    print("="*40)
    print(" FEYNMAP ANOMALY REPORT (DARK MATTER) ")
    print("="*40)
    
    if ghost_states:
        print(f"\n[!] GHOST STATES DETECTED ({len(ghost_states)}):")
        print("These nodes have no interaction paths and may be dead code.")
        for ghost in ghost_states:
            print(f"  - {ghost}")
    else:
        print("\n[✓] NO GHOST STATES: Every node is active in the Standard Model.")

    print(f"\n[SUCCESS] Ledger and Graph updated.")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    run_feynmap(path)
