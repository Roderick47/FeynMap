# FeynMap Integration Guide

## 🚀 Using FeynMap in New Projects

### 1. Installation Options

#### Option A: Install as Python Package (Recommended)
```bash
# From PyPI (when published)
pip install feynmap

# From source (current)
git clone https://github.com/feynmap/feynmap.git
cd feynmap
pip install -e .
```

#### Option B: Copy Files Directly
```bash
# Copy feynmap directory to your project
cp -r feynmap /path/to/your/project/
```

### 2. Quick Start in Any Project

```bash
# Navigate to your project directory
cd /path/to/your/project

# Auto-detect framework and analyze
feynmap .

# Specify framework if needed
feynmap . --framework django  # or flask, fastapi, rails, generic

# Analyze specific components
feynmap . --target-nodes "UserView,PostModel"
```

## 🤖 IDE Agent Integration

### 1. Python API Integration

Your IDE agent can use FeynMap programmatically:

```python
from feyn_parser import FeynExtractor
from feyn_notation import FeynNotator
import json

class FeynMapAgent:
    def __init__(self, project_path):
        self.project_path = project_path
        self.extractor = None
        self.graph_data = None
        self.ledger = None
    
    def analyze_project(self, framework='auto', target_nodes=None):
        """Analyze project and return structured data"""
        # Initialize extractor
        self.extractor = FeynExtractor(self.project_path, framework=framework)
        
        # Scan project
        self.graph_data = self.extractor.scan()
        
        # Apply lazy loading if target nodes specified
        if target_nodes:
            self.graph_data = self._extract_concerned_nodes(
                self.graph_data, target_nodes
            )
        
        # Generate physics notation
        self.ledger = self._generate_ledger()
        
        return {
            'graph_data': self.graph_data,
            'ledger': self.ledger,
            'framework': framework,
            'stats': self._get_stats()
        }
    
    def get_component_analysis(self, component_name):
        """Get detailed analysis of a specific component"""
        if not self.graph_data:
            self.analyze_project()
        
        # Find component in graph
        component = None
        for node in self.graph_data['nodes']:
            if node['id'] == component_name:
                component = node
                break
        
        if not component:
            return None
        
        # Get connections
        connections = []
        for edge in self.graph_data['edges']:
            if edge['source'] == component_name or edge['target'] == component_name:
                connections.append(edge)
        
        return {
            'component': component,
            'connections': connections,
            'notation': self.ledger.get(component_name),
            'complexity': component.get('metadata', {}).get('mass', 1.0),
            'dependencies': self._get_dependencies(component_name)
        }
    
    def find_ghost_states(self):
        """Identify unused/dead code"""
        if not self.graph_data:
            self.analyze_project()
        
        all_nodes = {node['id'] for node in self.graph_data['nodes']}
        used_nodes = set()
        
        # Find all referenced nodes
        for edge in self.graph_data['edges']:
            used_nodes.add(edge['source'])
            used_nodes.add(edge['target'])
        
        ghost_states = all_nodes - used_nodes
        return list(ghost_states)
    
    def get_framework_suggestions(self):
        """Get framework-specific suggestions"""
        if not self.graph_data:
            self.analyze_project()
        
        suggestions = []
        
        # Analyze patterns
        for node in self.graph_data['nodes']:
            if node['type'] == 'VERTEX':
                complexity = node.get('metadata', {}).get('mass', 1.0)
                if complexity > 1.5:
                    suggestions.append({
                        'type': 'complexity',
                        'component': node['id'],
                        'message': f"High complexity ({complexity}): Consider breaking down {node['id']}",
                        'severity': 'warning'
                    })
            
            elif node['type'] == 'PARTICLE':
                # Check for missing relationships
                has_relationships = any(
                    edge['source'] == node['id'] or edge['target'] == node['id']
                    for edge in self.graph_data['edges']
                )
                if not has_relationships:
                    suggestions.append({
                        'type': 'isolation',
                        'component': node['id'],
                        'message': f"Isolated model: {node['id']} has no relationships",
                        'severity': 'info'
                    })
        
        return suggestions
    
    def _extract_concerned_nodes(self, graph_data, target_nodes):
        """Extract subgraph for target nodes"""
        # Implementation from main.py
        concerned_nodes = set(target_nodes)
        concerned_edges = []
        node_queue = list(target_nodes)
        
        while node_queue:
            current_node = node_queue.pop(0)
            
            for edge in graph_data["edges"]:
                if edge["source"] == current_node or edge["target"] == current_node:
                    concerned_edges.append(edge)
                    
                    connected_node = edge["target"] if edge["source"] == current_node else edge["source"]
                    if connected_node not in concerned_nodes:
                        concerned_nodes.add(connected_node)
                        node_queue.append(connected_node)
        
        return {
            "nodes": [node for node in graph_data["nodes"] if node["id"] in concerned_nodes],
            "edges": concerned_edges
        }
    
    def _generate_ledger(self):
        """Generate physics notation ledger"""
        ledger = {}
        
        for node in self.graph_data["nodes"]:
            if node["type"] == "VERTEX":
                trace = [("PROPAGATOR_HTTP", "URL"), ("VERTEX", node["id"])]
                ledger[node["id"]] = FeynNotator.generate_enhanced_string(trace)
        
        return ledger
    
    def _get_stats(self):
        """Get analysis statistics"""
        node_types = {}
        for node in self.graph_data['nodes']:
            node_type = node['type']
            node_types[node_type] = node_types.get(node_type, 0) + 1
        
        return {
            'total_nodes': len(self.graph_data['nodes']),
            'total_edges': len(self.graph_data['edges']),
            'node_types': node_types,
            'ghost_states': len(self.find_ghost_states())
        }
    
    def _get_dependencies(self, component_name):
        """Get dependencies for a component"""
        dependencies = []
        for edge in self.graph_data['edges']:
            if edge['source'] == component_name:
                dependencies.append(edge['target'])
        return dependencies
```

### 2. IDE Agent Usage Examples

#### Context-Aware Code Suggestions
```python
# In your IDE agent
agent = FeynMapAgent('/path/to/project')

# Get context for current file
analysis = agent.analyze_project()

# When user opens a file
current_file = 'models.py'
suggestions = agent.get_framework_suggestions()

# Provide intelligent suggestions
for suggestion in suggestions:
    if suggestion['component'] in current_file:
        print(f"💡 {suggestion['message']}")
```

#### Smart Code Completion
```python
# When user types a model name
model_analysis = agent.get_component_analysis('UserModel')
if model_analysis:
    # Suggest related views
    related_views = [
        conn['target'] for conn in model_analysis['connections']
        if conn['type'] == 'PARTICLE_ENTANGLEMENT'
    ]
    print(f"Related views: {related_views}")
```

#### Refactoring Assistance
```python
# Find complex components that need refactoring
ghost_states = agent.find_ghost_states()
if ghost_states:
    print(f"👻 Found {len(ghost_states)} unused components:")
    for ghost in ghost_states:
        print(f"  - {ghost}")
```

### 3. VS Code Extension Integration

```javascript
// VS Code extension example
const vscode = require('vscode');
const { spawn } = require('child_process');

class FeynMapProvider {
    constructor() {
        this.projectPath = vscode.workspace.rootPath;
    }
    
    async analyzeProject() {
        return new Promise((resolve, reject) => {
            const feynmap = spawn('feynmap', [this.projectPath, '--framework', 'auto']);
            
            let output = '';
            feynmap.stdout.on('data', (data) => {
                output += data.toString();
            });
            
            feynmap.on('close', (code) => {
                if (code === 0) {
                    resolve(this.parseOutput(output));
                } else {
                    reject(new Error(`FeynMap failed with code ${code}`));
                }
            });
        });
    }
    
    async provideCodeActions(document, range) {
        const analysis = await this.analyzeProject();
        const actions = [];
        
        // Add code actions based on analysis
        analysis.suggestions.forEach(suggestion => {
            actions.push({
                title: suggestion.message,
                command: 'feynmap.applySuggestion',
                arguments: [suggestion]
            });
        });
        
        return actions;
    }
}
```

### 4. Real-time Analysis

```python
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class FeynMapWatcher(FileSystemEventHandler):
    def __init__(self, agent):
        self.agent = agent
        self.last_analysis = None
    
    def on_modified(self, event):
        if event.src_path.endswith('.py'):
            # Re-analyze on file changes
            asyncio.create_task(self.reanalyze())
    
    async def reanalyze(self):
        analysis = self.agent.analyze_project()
        
        # Check for new ghost states
        new_ghosts = self.agent.find_ghost_states()
        if new_ghosts != self.last_analysis.get('ghost_states', []):
            print(f"👻 New ghost states detected: {new_ghosts}")
        
        self.last_analysis = analysis

# Set up file watcher
def setup_realtime_analysis(project_path):
    agent = FeynMapAgent(project_path)
    event_handler = FeynMapWatcher(agent)
    
    observer = Observer()
    observer.schedule(event_handler, project_path, recursive=True)
    observer.start()
    
    return agent
```

## 🎯 IDE Agent Features

### 1. Smart Context Awareness
- **Current file context**: Understand what the user is working on
- **Project-wide analysis**: See the big picture
- **Dependency tracking**: Know how components relate

### 2. Intelligent Suggestions
- **Complexity warnings**: Flag overly complex components
- **Dead code detection**: Find unused components
- **Architecture insights**: Suggest improvements

### 3. Code Generation
- **Boilerplate generation**: Create new components following patterns
- **Refactoring assistance**: Suggest and apply refactorings
- **Documentation generation**: Auto-generate docs from analysis

### 4. Visual Integration
- **Interactive diagrams**: Show Feynman diagrams of code
- **Dependency graphs**: Visualize component relationships
- **Ghost state highlighting**: Show unused code

## 📋 Integration Checklist

### For IDE Developers:
- [ ] Install FeynMap as dependency
- [ ] Implement FeynMapAgent class
- [ ] Add file system watcher
- [ ] Create UI components for visualization
- [ ] Add command palette commands
- [ ] Implement code actions

### For Users:
- [ ] Install FeynMap in project
- [ ] Run initial analysis
- [ ] Configure framework if needed
- [ ] Set up real-time monitoring
- [ ] Customize suggestions

## 🚀 Getting Started

1. **Install FeynMap**: `pip install feynmap`
2. **Initialize Agent**: `agent = FeynMapAgent('/path/to/project')`
3. **Analyze**: `analysis = agent.analyze_project()`
4. **Get Insights**: `suggestions = agent.get_framework_suggestions()`
5. **Integrate**: Add to your IDE workflows

Your IDE agent now has superpowers! 🦸‍♂️
