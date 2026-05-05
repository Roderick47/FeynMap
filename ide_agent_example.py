#!/usr/bin/env python3
"""
Example of how an IDE agent can integrate with FeynMap
"""

import json
from pathlib import Path
from feyn_parser import FeynExtractor
from feyn_notation import FeynNotator

class FeynMapIDEAgent:
    """IDE Agent that uses FeynMap for intelligent code assistance"""
    
    def __init__(self, project_path):
        self.project_path = Path(project_path)
        self.extractor = None
        self.analysis_cache = None
        self.current_file = None
    
    def initialize(self):
        """Initialize the agent with project analysis"""
        print("🔍 Initializing FeynMap IDE Agent...")
        
        # Auto-detect framework and analyze
        self.extractor = FeynExtractor(self.project_path, framework='auto')
        graph_data = self.extractor.scan()
        
        # Cache analysis
        self.analysis_cache = {
            'graph_data': graph_data,
            'ledger': self._generate_ledger(graph_data),
            'framework': self._detect_framework(graph_data)
        }
        
        print(f"✅ Initialized with {self.analysis_cache['framework']} framework")
        print(f"📊 Analyzed {len(graph_data['nodes'])} components")
        
        return self.analysis_cache
    
    def get_context_for_file(self, file_path):
        """Get relevant context when user opens a file"""
        if not self.analysis_cache:
            self.initialize()
        
        self.current_file = Path(file_path)
        file_name = self.current_file.name
        
        # Find components in this file
        components_in_file = []
        for node in self.analysis_cache['graph_data']['nodes']:
            if node.get('file') == file_name:
                components_in_file.append(node)
        
        context = {
            'file': file_name,
            'components': components_in_file,
            'suggestions': self._get_file_suggestions(components_in_file),
            'related_components': self._get_related_components(components_in_file)
        }
        
        return context
    
    def suggest_next_action(self, current_line=None, current_text=None):
        """Suggest next action based on current context"""
        if not self.current_file or not self.analysis_cache:
            return []
        
        suggestions = []
        
        # Get current component
        current_component = self._get_current_component()
        if not current_component:
            return suggestions
        
        # Analyze what user might be doing
        if current_text:
            if 'class' in current_text and 'View' in current_text:
                suggestions.append({
                    'type': 'pattern',
                    'message': '🎯 Creating a new View - consider adding corresponding Model and Serializer',
                    'action': 'create_related_components'
                })
            
            elif 'models.' in current_text or 'ForeignKey' in current_text:
                suggestions.append({
                    'type': 'pattern',
                    'message': '🔗 Defining model relationships - check for proper indexing',
                    'action': 'suggest_model_optimizations'
                })
            
            elif 'serializer' in current_text.lower():
                suggestions.append({
                    'type': 'pattern',
                    'message': '📝 Creating serializer - ensure all required fields are included',
                    'action': 'validate_serializer_fields'
                })
        
        # Add complexity-based suggestions
        complexity = current_component.get('metadata', {}).get('mass', 1.0)
        if complexity > 1.5:
            suggestions.append({
                'type': 'complexity',
                'message': f'⚠️ High complexity ({complexity}) - consider breaking down into smaller components',
                'action': 'suggest_refactoring'
            })
        
        return suggestions
    
    def find_unused_imports(self, file_path):
        """Find unused imports in a file"""
        if not self.analysis_cache:
            self.initialize()
        
        # This is a simplified example
        # In practice, you'd parse the file and cross-reference with usage
        file_name = Path(file_path).name
        
        unused_imports = []
        for node in self.analysis_cache['graph_data']['nodes']:
            if node.get('file') == file_name and node['type'] == 'VERTEX':
                # Check if this view has model connections
                has_model_connection = any(
                    edge['source'] == node['id'] and edge['type'] == 'PARTICLE_ENTANGLEMENT'
                    for edge in self.analysis_cache['graph_data']['edges']
                )
                
                if not has_model_connection and 'models' in file_name:
                    unused_imports.append(f"Potential unused model import in {node['id']}")
        
        return unused_imports
    
    def generate_component_template(self, framework, component_type, name):
        """Generate template for new component"""
        
        templates = {
            'django': {
                'model': f"""
class {name}(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "{name}"
        verbose_name_plural = "{name}s"

    def __str__(self):
        return self.name
""",
                'view': f"""
class {name}View(ListView):
    model = {name}
    template_name = '{name.lower()}/{name.lower()}_list.html'
    context_object_name = '{name.lower()}s'

class {name}DetailView(DetailView):
    model = {name}
    template_name = '{name.lower()}/{name.lower()}_detail.html'
    context_object_name = '{name.lower()}'

class {name}CreateView(CreateView):
    model = {name}
    template_name = '{name.lower()}/{name.lower()}_form.html'
    fields = ['name']
    success_url = reverse_lazy('{name.lower()}_list')
""",
                'serializer': f"""
class {name}Serializer(serializers.ModelSerializer):
    class Meta:
        model = {name}
        fields = ['id', 'name', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
"""
            },
            'flask': {
                'model': f"""
class {name}(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<{name} {{self.name}}>'
""",
                'view': f"""
@{name.lower()}_bp.route('/{name.lower()}s')
def list_{name.lower()}():
    {name.lower()}s = {name}.query.all()
    return render_template('{name.lower()}/list.html', {name.lower()}s={name.lower()}s)

@{name.lower()}_bp.route('/{name.lower()}s/<int:id>')
def detail_{name.lower()}(id):
    {name.lower()} = {name}.query.get_or_404(id)
    return render_template('{name.lower()}/detail.html', {name.lower()}={name.lower()})
"""
            }
        }
        
        return templates.get(framework, {}).get(component_type, f"# Template for {component_type} '{name}' not available for {framework}")
    
    def get_architecture_overview(self):
        """Get high-level architecture overview"""
        if not self.analysis_cache:
            self.initialize()
        
        graph_data = self.analysis_cache['graph_data']
        
        # Count component types
        component_counts = {}
        for node in graph_data['nodes']:
            comp_type = node['type']
            component_counts[comp_type] = component_counts.get(comp_type, 0) + 1
        
        # Find most connected components
        connection_counts = {}
        for edge in graph_data['edges']:
            source = edge['source']
            target = edge['target']
            connection_counts[source] = connection_counts.get(source, 0) + 1
            connection_counts[target] = connection_counts.get(target, 0) + 1
        
        most_connected = sorted(connection_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Find ghost states
        all_nodes = {node['id'] for node in graph_data['nodes']}
        used_nodes = set()
        for edge in graph_data['edges']:
            used_nodes.add(edge['source'])
            used_nodes.add(edge['target'])
        ghost_states = list(all_nodes - used_nodes)
        
        return {
            'framework': self.analysis_cache['framework'],
            'component_counts': component_counts,
            'most_connected': most_connected,
            'ghost_states': ghost_states,
            'total_components': len(graph_data['nodes']),
            'total_connections': len(graph_data['edges'])
        }
    
    def _generate_ledger(self, graph_data):
        """Generate physics notation ledger"""
        ledger = {}
        for node in graph_data["nodes"]:
            if node["type"] == "VERTEX":
                trace = [("PROPAGATOR_HTTP", "URL"), ("VERTEX", node["id"])]
                ledger[node["id"]] = FeynNotator.generate_enhanced_string(trace)
        return ledger
    
    def _detect_framework(self, graph_data):
        """Detect which framework this project uses"""
        # Simple heuristic based on component patterns
        has_django_patterns = any(
            node['type'] == 'VERTEX' and 'View' in node['id']
            for node in graph_data['nodes']
        )
        
        has_flask_patterns = any(
            node['type'] == 'PARTICLE' and 'db.Model' in str(node.get('metadata', {}))
            for node in graph_data['nodes']
        )
        
        if has_django_patterns:
            return 'django'
        elif has_flask_patterns:
            return 'flask'
        else:
            return 'generic'
    
    def _get_file_suggestions(self, components):
        """Get suggestions for components in current file"""
        suggestions = []
        
        for component in components:
            complexity = component.get('metadata', {}).get('mass', 1.0)
            if complexity > 1.5:
                suggestions.append({
                    'component': component['id'],
                    'type': 'complexity',
                    'message': f"High complexity ({complexity}): Consider breaking down {component['id']}"
                })
        
        return suggestions
    
    def _get_related_components(self, components):
        """Get components related to those in current file"""
        related = []
        current_ids = {comp['id'] for comp in components}
        
        for edge in self.analysis_cache['graph_data']['edges']:
            if edge['source'] in current_ids:
                related.append(edge['target'])
            elif edge['target'] in current_ids:
                related.append(edge['source'])
        
        return list(set(related))
    
    def _get_current_component(self):
        """Get the component being currently edited"""
        if not self.current_file or not self.analysis_cache:
            return None
        
        file_name = self.current_file.name
        for node in self.analysis_cache['graph_data']['nodes']:
            if node.get('file') == file_name:
                return node
        
        return None


# Example usage
if __name__ == "__main__":
    # Initialize IDE agent
    agent = FeynMapIDEAgent('.')
    
    # Initialize with project analysis
    analysis = agent.initialize()
    
    # Get context for a file
    context = agent.get_context_for_file('feyn_parser.py')
    print(f"\n📁 Context for feyn_parser.py:")
    print(f"  Components: {len(context['components'])}")
    print(f"  Suggestions: {len(context['suggestions'])}")
    
    # Get architecture overview
    overview = agent.get_architecture_overview()
    print(f"\n🏗️  Architecture Overview:")
    print(f"  Framework: {overview['framework']}")
    print(f"  Total components: {overview['total_components']}")
    print(f"  Total connections: {overview['total_connections']}")
    print(f"  Component types: {overview['component_counts']}")
    
    # Generate template
    template = agent.generate_component_template('django', 'model', 'BlogPost')
    print(f"\n📝 Generated template:")
    print(template[:200] + "..." if len(template) > 200 else template)
