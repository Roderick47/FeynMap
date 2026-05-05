import os
import ast
import re
from pathlib import Path
try:
    from .config import get_framework_config, DEFAULT_CONFIG
except ImportError:
    from config import get_framework_config, DEFAULT_CONFIG

class FeynExtractor:
    def __init__(self, project_path, framework='auto'):
        self.project_path = Path(project_path)
        self.config = get_framework_config(framework)
        self.graph = {"nodes": [], "edges": []}
        self.node_ids = set()  # Track existing node IDs to avoid duplicates

    def scan(self):
        for root, _, files in os.walk(self.project_path):
            if any(x in root for x in self.config.exclude_dirs):
                continue
            for file in files:
                file_path = Path(root) / file
                if any(file.endswith(ext) for ext in self.config.code_extensions):
                    self._parse_code(file_path)
                elif any(file.endswith(ext) for ext in self.config.template_extensions):
                    self._parse_template(file_path)
        return self.graph

    def _add_node(self, node_id, node_type, file_name, **kwargs):
        """Add a node if it doesn't already exist with enhanced metadata"""
        if node_id not in self.node_ids:
            self.node_ids.add(node_id)
            node_data = {
                "id": node_id, 
                "type": node_type, 
                "file": file_name,
                "metadata": self._calculate_metadata(node_id, node_type, file_name, **kwargs)
            }
            node_data.update(kwargs)
            self.graph["nodes"].append(node_data)
    
    def _calculate_metadata(self, node_id, node_type, file_name, **kwargs):
        """Calculate physics-inspired metadata for nodes"""
        metadata = {
            "mass": 1.0,  # Base complexity
            "charge": 1.0,  # Base importance
            "spin": 0.5,   # Base rotation/changes
            "energy": 0.5, # Base activity level
            "coupling": 0.5, # Base coupling strength
            "lifetime": 1.0, # Base stability
            "file": file_name,
            "lines": kwargs.get("lines", 0)
        }
        
        # Calculate complexity based on node type and properties
        if node_type == "VERTEX":
            # Views have higher mass based on their complexity
            metadata["mass"] = self._calculate_view_complexity(node_id, file_name)
            metadata["energy"] = 0.8  # Views are active components
        elif node_type == "PARTICLE":
            # Models have mass based on field count and relations
            metadata["mass"] = self._calculate_model_complexity(node_id, file_name)
            metadata["charge"] = 1.2  # Models are important (high charge)
        elif node_type == "TRANSFORM":
            # Serializers have medium mass but high coupling
            metadata["mass"] = 0.6
            metadata["coupling"] = 0.8
        elif node_type == "FRONTEND":
            # Templates have variable mass based on content
            metadata["mass"] = self._calculate_template_complexity(node_id, file_name)
        elif node_type == "JAVASCRIPT":
            # JS functions have lower mass but higher energy
            metadata["mass"] = 0.3
            metadata["energy"] = 0.9
        elif node_type == "AJAX":
            # AJAX calls have high energy (fast interactions)
            metadata["energy"] = 1.0
            metadata["coupling"] = 0.7
        
        return metadata
    
    def _calculate_view_complexity(self, view_name, file_name):
        """Calculate complexity mass for view classes"""
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Count lines in the view class
            lines = len([line for line in content.split('\n') if line.strip()])
            
            # Base complexity on lines and methods
            complexity = min(lines / 100.0, 2.0)  # Normalize to 0-2 range
            
            # Add complexity for common patterns
            if "CreateView" in view_name:
                complexity += 0.3
            if "UpdateView" in view_name:
                complexity += 0.2
            if "ListView" in view_name:
                complexity += 0.1
            if "DetailView" in view_name:
                complexity += 0.1
            
            return round(complexity, 2)
        except:
            return 1.0
    
    def _calculate_model_complexity(self, model_name, file_name):
        """Calculate complexity mass for model classes"""
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Count fields and relationships
            field_count = content.count('models.')
            relationship_count = content.count('ForeignKey') + content.count('ManyToManyField')
            
            complexity = 0.5 + (field_count * 0.1) + (relationship_count * 0.2)
            return round(min(complexity, 2.0), 2)
        except:
            return 1.0
    
    def _calculate_template_complexity(self, template_name, file_name):
        """Calculate complexity mass for templates"""
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Count template variables, tags, and JavaScript
            var_count = len(re.findall(r'{{\s*[\w\.]+\s*}}', content))
            tag_count = len(re.findall(r'{%\s*[^%]+\s*%}', content))
            js_count = len(re.findall(r'function\s+\w+', content))
            
            complexity = 0.3 + (var_count * 0.05) + (tag_count * 0.1) + (js_count * 0.15)
            return round(min(complexity, 2.0), 2)
        except:
            return 0.5

    def _parse_code(self, path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read())
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        current_class = node.name
                        
                        # Detect Models (Particles) using framework config
                        if self._matches_pattern(node, self.config.get_model_detection_rules()):
                            self._add_node(node.name, "PARTICLE", path.name)
                        
                        # Detect Views (Vertices) using framework config
                        if self._matches_pattern(node, self.config.get_view_detection_rules()):
                            self._add_node(node.name, "VERTEX", path.name)
                        
                        # Detect Serializers (Transitions) using framework config
                        if self._matches_pattern(node, self.config.get_serializer_detection_rules()):
                            self._add_node(node.name, "TRANSFORM", path.name)
                        
                        # Particle Entanglement: Check for model assignments inside this class
                        for child in ast.walk(node):
                            if isinstance(child, ast.Assign):
                                for target in child.targets:
                                    if isinstance(target, ast.Name) and target.id == "model":
                                        # Found model = ModelName assignment
                                        if isinstance(child.value, ast.Name):
                                            model_name = child.value.id
                                            # Create Particle node for the referenced model
                                            self._add_node(model_name, "PARTICLE", path.name, imported=True)
                                            # Create edge from View (Vertex) to Model (Particle)
                                            self.graph["edges"].append({
                                                "source": current_class, 
                                                "target": model_name, 
                                                "type": "PARTICLE_ENTANGLEMENT"
                                            })
                                    elif isinstance(target, ast.Name) and target.id == "serializer_class":
                                        # Found serializer_class = SerializerName assignment
                                        if isinstance(child.value, ast.Name):
                                            serializer_name = child.value.id
                                            # Create Transform node for the referenced serializer
                                            self._add_node(serializer_name, "TRANSFORM", path.name, imported=True)
                                            # Create edge from View (Vertex) to Serializer (Transform)
                                            self.graph["edges"].append({
                                                "source": current_class, 
                                                "target": serializer_name, 
                                                "type": "SERIALIZER_ENTANGLEMENT"
                                            })
                    
                    elif isinstance(node, ast.FunctionDef):
                        # Detect function-based views (vertices) using framework config
                        if self._matches_function_pattern(node, self.config.get_view_detection_rules()):
                            self._add_node(node.name, "VERTEX", path.name)
                            
                            # Look for model usage in function-based views
                            for child in ast.walk(node):
                                if isinstance(child, ast.Call):
                                    if isinstance(child.func, ast.Attribute):
                                        # Look for ORM patterns using framework config
                                        if hasattr(child.func, 'value') and isinstance(child.func.value, ast.Name):
                                            model_name = child.func.value.id
                                            # Check if this matches any ORM pattern
                                            if self._matches_orm_pattern(ast.unparse(child)):
                                                # Create edge from function view to model
                                                self.graph["edges"].append({
                                                    "source": node.name,
                                                    "target": model_name,
                                                    "type": "PARTICLE_ENTANGLEMENT"
                                                })
            except: pass

    def _parse_template(self, path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            
            # Add template as frontend node
            template_name = path.stem
            self._add_node(template_name, "FRONTEND", path.name)
            
            # Parse template patterns using framework config
            template_patterns = self.config.get_template_patterns()
            
            if template_patterns:
                # Parse template variables
                if "variables" in template_patterns:
                    vars = re.findall(template_patterns["variables"], content)
                    for v in vars:
                        self.graph["edges"].append({"source": template_name, "target": v.split('.')[0], "type": "OBSERVATION"})
                
                # Parse JavaScript functions
                if "js_functions" in template_patterns:
                    js_functions = re.findall(template_patterns["js_functions"], content)
                    for func in js_functions:
                        self._add_node(func, "JAVASCRIPT", path.name)
                        self.graph["edges"].append({"source": template_name, "target": func, "type": "EVENT"})
                
                # Parse arrow functions and event handlers
                if "arrow_functions" in template_patterns:
                    arrow_functions = re.findall(template_patterns["arrow_functions"], content)
                    for func in arrow_functions:
                        if func not in ['console', 'document', 'window', 'navigator']:  # Skip global objects
                            self._add_node(func, "JAVASCRIPT", path.name)
                            self.graph["edges"].append({"source": template_name, "target": func, "type": "EVENT"})
                
                # Parse AJAX/fetch calls
                if "fetch_calls" in template_patterns:
                    fetch_calls = re.findall(template_patterns["fetch_calls"], content)
                    for endpoint in fetch_calls:
                        # Extract view name from URL
                        view_name = endpoint.strip('/').replace('-', '_').replace('/', '_')
                        self._add_node(endpoint, "AJAX", path.name)
                        self.graph["edges"].append({"source": template_name, "target": endpoint, "type": "AJAX"})
                
                # Parse async/await patterns
                if "async_functions" in template_patterns:
                    async_functions = re.findall(template_patterns["async_functions"], content)
                    for func in async_functions:
                        self._add_node(func, "JAVASCRIPT", path.name)
                        self.graph["edges"].append({"source": template_name, "target": func, "type": "VIRTUAL"})
            
            # Parse external dependencies
            dependencies = []
            
            # Leaflet.js detection
            if 'L.map(' in content or 'L.marker(' in content:
                dependencies.append('Leaflet')
            
            # Other common libraries
            if 'jQuery' in content or '$(' in content:
                dependencies.append('jQuery')
            if 'bootstrap' in content.lower():
                dependencies.append('Bootstrap')
            if 'axios' in content:
                dependencies.append('Axios')
            
            for dep in dependencies:
                self._add_node(dep, "DEPENDENCY", path.name)
                self.graph["edges"].append({"source": template_name, "target": dep, "type": "DEPENDENCY"})
            
            # Parse event listeners using framework config
            if template_patterns and "event_listeners" in template_patterns:
                event_listeners = re.findall(template_patterns["event_listeners"], content)
                for event in event_listeners:
                    self._add_node(f"{event}_handler", "EVENT", path.name)
                    self.graph["edges"].append({"source": template_name, "target": f"{event}_handler", "type": "EVENT"})

    def _matches_pattern(self, node, patterns):
        """Check if AST node matches any of the given patterns"""
        for pattern in patterns:
            pattern_type = pattern.get("type")
            pattern_value = pattern.get("pattern")
            
            if pattern_type == "class_inheritance":
                # Check for inheritance patterns like 'models.Model'
                for base in node.bases:
                    if hasattr(base, 'attr') and base.attr == pattern_value:
                        return True
                    elif hasattr(base, 'id') and base.id == pattern_value:
                        return True
                    elif hasattr(base, 'value') and hasattr(base.value, 'id') and base.value.id == pattern_value:
                        return True
                        
            elif pattern_type == "class_name_suffix":
                # Check if class name ends with pattern
                if isinstance(pattern_value, str):
                    if node.name.endswith(pattern_value):
                        return True
                elif isinstance(pattern_value, list):
                    if any(node.name.endswith(suffix) for suffix in pattern_value):
                        return True
                        
            elif pattern_type == "class_decoration":
                # Check for class decorators
                for decorator in node.decorator_list:
                    if hasattr(decorator, 'attr') and decorator.attr == pattern_value:
                        return True
                    elif hasattr(decorator, 'id') and decorator.id == pattern_value:
                        return True
                        
        return False
    
    def _matches_function_pattern(self, node, patterns):
        """Check if function matches any of the given patterns"""
        for pattern in patterns:
            pattern_type = pattern.get("type")
            pattern_value = pattern.get("pattern")
            
            if pattern_type == "function_decorator":
                # Check for function decorators
                for decorator in node.decorator_list:
                    if hasattr(decorator, 'attr') and decorator.attr.startswith(pattern_value):
                        return True
                    elif hasattr(decorator, 'id') and decorator.id.startswith(pattern_value):
                        return True
                        
            elif pattern_type == "function_name_contains":
                # Check if function name contains pattern
                if isinstance(pattern_value, str):
                    if pattern_value in node.name.lower():
                        return True
                elif isinstance(pattern_value, list):
                    if any(pattern in node.name.lower() for pattern in pattern_value):
                        return True
                        
        return False
    
    def _matches_orm_pattern(self, code_str):
        """Check if code string matches any ORM patterns"""
        for pattern in self.config.get_orm_patterns():
            if re.search(pattern, code_str):
                return True
        return False

