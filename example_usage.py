#!/usr/bin/env python3
"""
Example usage of portable FeynMap with different frameworks
"""

from feyn_parser import FeynExtractor
from feyn_notation import FeynNotator

def analyze_project(project_path, framework='auto'):
    """Analyze a project using specified framework"""
    print(f"🔍 Analyzing {project_path} with {framework} framework...")
    
    # Initialize extractor with framework
    extractor = FeynExtractor(project_path, framework=framework)
    graph_data = extractor.scan()
    
    # Print basic statistics
    print(f"📊 Found {len(graph_data['nodes'])} nodes and {len(graph_data['edges'])} edges")
    
    # Generate physics-inspired notation for each node
    ledger = {}
    enhanced_ledger = {}
    
    for node in graph_data["nodes"]:
        if node["type"] == "VERTEX":
            # Build interaction trace for backend views
            trace = []
            metadata_map = {}
            
            trace.append(("PROPAGATOR_HTTP", "URL"))
            metadata_map[0] = {"mass": 0.1, "energy": 1.0, "coupling": 0.9}
            
            trace.append(("VERTEX", node["id"]))
            metadata_map[1] = node.get("metadata", {})
            
            # Generate notation
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
    
    # Print results
    if ledger:
        print("\n🎯 Physics-Inspired Notation:")
        for node_id, notation in ledger.items():
            print(f"  {node_id}: {notation}")
    
    return graph_data, enhanced_ledger

def demonstrate_frameworks():
    """Demonstrate different framework configurations"""
    
    print("=" * 60)
    print("🚀 FEYNMAP PORTABILITY DEMONSTRATION")
    print("=" * 60)
    
    # Test with current directory using different frameworks
    frameworks = ['django', 'flask', 'fastapi', 'generic']
    
    for framework in frameworks:
        print(f"\n{'='*20} {framework.upper()} {'='*20}")
        try:
            graph_data, enhanced_ledger = analyze_project('.', framework)
            
            # Show framework-specific patterns
            if graph_data['nodes']:
                print(f"✅ Successfully detected {len(graph_data['nodes'])} components")
                for node in graph_data['nodes'][:3]:  # Show first 3 nodes
                    print(f"  - {node['type']}: {node['id']}")
            else:
                print("ℹ️  No framework-specific components found (expected for non-matching frameworks)")
                
        except Exception as e:
            print(f"❌ Error with {framework}: {e}")

if __name__ == "__main__":
    demonstrate_frameworks()
