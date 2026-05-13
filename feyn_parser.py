import os
import ast
import re
import logging
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple

try:
    from .config import get_framework_config, DEFAULT_CONFIG
except ImportError:
    from config import get_framework_config, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# Constants for complexity calculations
class ComplexityDefaults:
    """Default values for complexity calculations"""
    DEFAULT_MASS = 1.0
    DEFAULT_CHARGE = 1.0
    DEFAULT_SPIN = 0.5
    DEFAULT_ENERGY = 0.5
    DEFAULT_COUPLING = 0.5
    DEFAULT_LIFETIME = 1.0
    
    # Complexity bounds
    COMPLEXITY_MAX = 2.0
    COMPLEXITY_MIN = 0.0
    
    # View complexity modifiers
    VIEW_CREATEVIEW_BONUS = 0.3
    VIEW_UPDATEVIEW_BONUS = 0.2
    VIEW_LISTVIEW_BONUS = 0.1
    VIEW_DETAILVIEW_BONUS = 0.1
    VIEW_BASE_COMPLEXITY_DIVISOR = 100.0
    VIEW_ENERGY = 0.8
    
    # Model complexity
    MODEL_BASE = 0.5
    MODEL_FIELD_WEIGHT = 0.1
    MODEL_RELATION_WEIGHT = 0.2
    MODEL_CHARGE = 1.2
    
    # Serializer/Transform
    TRANSFORM_MASS = 0.6
    TRANSFORM_COUPLING = 0.8
    
    # JavaScript
    JAVASCRIPT_MASS = 0.3
    JAVASCRIPT_ENERGY = 0.9
    
    # AJAX
    AJAX_ENERGY = 1.0
    AJAX_COUPLING = 0.7
    
    # Template
    TEMPLATE_BASE = 0.3
    TEMPLATE_VAR_WEIGHT = 0.05
    TEMPLATE_TAG_WEIGHT = 0.1
    TEMPLATE_JS_WEIGHT = 0.15
    TEMPLATE_DEFAULT = 0.5

# Regular expressions - compiled for better performance
class RegexPatterns:
    """Precompiled regex patterns for template parsing"""
    TEMPLATE_VARIABLES = re.compile(r'{{\s*[\w\.]+\s*}}')
    TEMPLATE_TAGS = re.compile(r'{%\s*[^%]+\s*%}')
    JS_FUNCTIONS = re.compile(r'function\s+\w+')
    LEAFLET_MAP = re.compile(r'L\.(map|marker)\(')
    JQUERY = re.compile(r'\$\(|jQuery')
    BOOTSTRAP = re.compile(r'bootstrap', re.IGNORECASE)
    AXIOS = re.compile(r'axios')


class FeynExtractor:
    """Extract framework components and build a dependency graph"""
    
    # Global objects to skip in JavaScript analysis
    GLOBAL_JS_OBJECTS = {'console', 'document', 'window', 'navigator'}

    # BUG-02 fix: ORM/stdlib method names that must not become shared mediator
    # nodes. These are attribute calls on querysets, model instances, or Python
    # builtins — not project-defined callables — and would otherwise create
    # spurious cross-view CALL edges all converging on a single 'get' node.
    ORM_BUILTIN_SKIP = {
        'get', 'filter', 'all', 'create', 'save', 'delete', 'update',
        'first', 'last', 'count', 'exists', 'exclude', 'values',
        'values_list', 'select_related', 'prefetch_related', 'order_by',
        'annotate', 'aggregate', 'bulk_create', 'bulk_update', 'get_or_create',
        'update_or_create', 'defer', 'only', 'using', 'none', 'union',
        'intersection', 'difference', 'raw', 'append', 'pop', 'add', 'remove',
        'clear', 'set', 'items', 'keys', 'values', 'encode', 'decode',
        'format', 'strip', 'split', 'join', 'lower', 'upper', 'replace',
        'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict',
        'tuple', 'set', 'bool', 'type', 'isinstance', 'hasattr', 'getattr',
        'setattr', 'super', 'zip', 'map', 'filter', 'sorted', 'enumerate',
        'open', 'read', 'write', 'close',
    }
    
    def __init__(self, project_path: str, framework: str = 'auto') -> None:
        """
        Initialize the Feyn extractor.
        
        Args:
            project_path: Root path of the project to analyze
            framework: Framework type ('auto', 'django', etc.)
            
        Raises:
            ValueError: If project_path does not exist
        """
        self.project_path = Path(project_path)
        
        if not self.project_path.exists():
            raise ValueError(f"Project path does not exist: {self.project_path}")
        
        self.config = get_framework_config(framework)
        self.graph: Dict[str, List[Any]] = {"nodes": [], "edges": []}
        self.node_ids: Set[str] = set()
        self._edge_ids: Set[Tuple[str, str, str]] = set()
        self._file_content_cache: Dict[str, str] = {}
        self.callable_defs: Dict[str, str] = {}

        # IMP-01: cross-app import resolution
        # symbol name → canonical source file, populated before edge extraction.
        self._symbol_to_file: Dict[str, str] = {}

        # IMP-02: URL pattern registry
        # view name → URL pattern string, populated by _parse_all_urls().
        # Views absent here after URL parsing are marked 'unrouted'.
        self._url_map: Dict[str, str] = {}

        # IMP-03: permission class registry
        # view node id → list of permission class names.
        self._permissions: Dict[str, List[str]] = {}

    def scan(self) -> Dict[str, List[Any]]:
        """
        Scan project for components and build dependency graph.
        
        Returns:
            Graph with nodes and edges representing project structure
        """
        excluded_dirs_set = set(self.config.exclude_dirs)
        code_extensions = tuple(self.config.code_extensions)
        template_extensions = tuple(self.config.template_extensions)
        
        try:
            code_paths: List[Path] = []
            template_paths: List[Path] = []

            for root, _, files in os.walk(self.project_path):
                if any(excluded_dir in root for excluded_dir in excluded_dirs_set):
                    continue
                
                for file in files:
                    file_path = Path(root) / file
                    
                    if file.endswith(code_extensions):
                        code_paths.append(file_path)
                    elif file.endswith(template_extensions):
                        template_paths.append(file_path)

            self._collect_callable_definitions(code_paths)

            # IMP-01: resolve cross-app imports before edge extraction so CALL
            # edges target the correct source module regardless of scan order.
            self._build_import_map(code_paths)

            # IMP-02: parse all urls.py files to build the view→URL map before
            # node annotation, so the url_pattern field is set on first write.
            self._parse_all_urls(code_paths)

            for file_path in code_paths:
                self._parse_code(file_path)
            for file_path in template_paths:
                self._parse_template(file_path)

            # IMP-02 post-pass: annotate VERTEX nodes with their URL pattern and
            # flag any that were never registered in any urlpatterns.
            self._annotate_url_metadata()

            # IMP-03 post-pass: write permission metadata onto VERTEX nodes.
            self._annotate_permission_metadata()

        except Exception as e:
            logger.error(f"Error scanning project: {e}")
        
        return self.graph

    def _add_node(self, node_id: str, node_type: str, file_name: str, **kwargs) -> None:
        """
        Add a node to the graph if it doesn't already exist.
        
        Args:
            node_id: Unique identifier for the node
            node_type: Type of node (e.g., 'PARTICLE', 'VERTEX')
            file_name: Source file name
            **kwargs: Additional node properties
        """
        node_data = {
            "id": node_id,
            "type": node_type,
            "file": file_name,
            "metadata": self._calculate_metadata(node_id, node_type, file_name, **kwargs)
        }
        node_data.update(kwargs)

        if node_id not in self.node_ids:
            self.node_ids.add(node_id)
            self.graph["nodes"].append(node_data)
            return

        # Imported placeholder nodes are often discovered from relationships
        # before their definitions are parsed. Upgrade placeholders with exact
        # source spans when the real definition is later encountered.
        if not kwargs.get("imported"):
            for existing_node in self.graph["nodes"]:
                if existing_node["id"] == node_id and existing_node.get("imported"):
                    existing_node.update(node_data)
                    existing_node.pop("imported", None)
                    break

    def _add_edge(self, source: str, target: str, edge_type: str, **kwargs) -> None:
        """Add a directed edge to the graph, avoiding duplicate relationships."""
        edge_key = (source, target, edge_type)
        if edge_key in self._edge_ids:
            return

        self._edge_ids.add(edge_key)
        edge_data = {
            "source": source,
            "target": target,
            "type": edge_type
        }
        edge_data.update(kwargs)
        self.graph["edges"].append(edge_data)

    def _collect_callable_definitions(self, paths: List[Path]) -> None:
        """Collect project-local callables before extracting call-chain edges."""
        for path in paths:
            content = self._read_file_content(str(path))
            if not content:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                logger.warning(f"Syntax error parsing {path}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error collecting callables from {path}: {e}")
                continue

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.callable_defs.setdefault(node.name, str(path))
                if isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.callable_defs.setdefault(child.name, str(path))

    # ------------------------------------------------------------------ #
    # IMP-01: Cross-app import resolution                                  #
    # ------------------------------------------------------------------ #

    def _build_import_map(self, paths: List[Path]) -> None:
        """
        Build a symbol→file map from all import statements across the project.

        This lets _process_callable_body resolve CALL edge targets to their
        true source file even when the caller and callee live in different apps,
        making cross-app dependency edges reliable regardless of scan order.
        """
        for path in paths:
            content = self._read_file_content(str(path))
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except (SyntaxError, Exception):
                continue

            for node in ast.walk(tree):
                # from <module> import <name1>, <name2>, ...
                if isinstance(node, ast.ImportFrom) and node.names:
                    for alias in node.names:
                        name = alias.asname or alias.name
                        # Resolve module path relative to project root if possible.
                        resolved = self._resolve_module_path(node.module, path)
                        self._symbol_to_file[name] = resolved or str(path)
                # import <module>
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name.split(".")[0]
                        self._symbol_to_file.setdefault(name, str(path))

    def _resolve_module_path(self, module: Optional[str], importer: Path) -> Optional[str]:
        """
        Convert a dotted module string to an absolute file path.

        Tries relative-to-project-root resolution first, then falls back to
        sibling-directory resolution so that both 'from payments.services import x'
        and 'from .services import x' are handled.
        """
        if not module:
            return None
        parts = module.replace(".", "/")
        # Try project-root-relative resolution
        candidate = self.project_path / (parts + ".py")
        if candidate.exists():
            return str(candidate)
        candidate_pkg = self.project_path / parts / "__init__.py"
        if candidate_pkg.exists():
            return str(candidate_pkg)
        # Try sibling of the importing file
        sibling = importer.parent / (parts.split("/")[-1] + ".py")
        if sibling.exists():
            return str(sibling)
        return None

    # ------------------------------------------------------------------ #
    # IMP-02: URL pattern parsing                                          #
    # ------------------------------------------------------------------ #

    def _parse_all_urls(self, paths: List[Path]) -> None:
        """
        Parse every urls.py / url_conf.py found in the project and populate
        self._url_map with view_name → url_pattern entries.

        Handles both class-based views (MyView.as_view()) and function views
        (my_view) registered via path(), re_path(), or url().
        """
        url_files = [p for p in paths if p.name in ("urls.py", "url_conf.py", "urls_api.py")]
        for path in url_files:
            content = self._read_file_content(str(path))
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except (SyntaxError, Exception):
                continue
            self._extract_url_patterns(tree)

    def _extract_url_patterns(self, tree: ast.AST) -> None:
        """Walk an AST and extract path()/re_path()/url() registrations."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = self._extract_call_name(node)
            if func_name not in ("path", "re_path", "url"):
                continue
            if len(node.args) < 2:
                continue
            # First arg is the URL pattern string
            url_arg = node.args[0]
            url_str = ast.literal_eval(url_arg) if isinstance(url_arg, ast.Constant) else None
            if not isinstance(url_str, str):
                continue
            # Second arg is the view — could be MyView.as_view() or a bare name
            view_arg = node.args[1]
            view_name = self._extract_view_name_from_arg(view_arg)
            if view_name:
                self._url_map.setdefault(view_name, url_str)

    def _extract_view_name_from_arg(self, node: ast.expr) -> Optional[str]:
        """
        Extract the view class or function name from a urlpattern view argument.

        Handles:
          - MyView.as_view()          → 'MyView'
          - my_function_view          → 'my_function_view'
          - views.MyView.as_view()    → 'MyView'
        """
        # Class-based: MyView.as_view(...)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "as_view":
                inner = func.value
                if isinstance(inner, ast.Name):
                    return inner.id
                if isinstance(inner, ast.Attribute):
                    return inner.attr
        # Function-based: bare name or module.name
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _annotate_url_metadata(self) -> None:
        """
        After all code files are parsed, write url_pattern and unrouted flag
        onto every VERTEX node in the graph.
        """
        for node in self.graph["nodes"]:
            if node["type"] != "VERTEX":
                continue
            nid = node["id"]
            url = self._url_map.get(nid)
            node["metadata"]["url_pattern"] = url
            # True when the view exists in code but is absent from all urls.py
            node["metadata"]["unrouted"] = (url is None) and bool(self._url_map)

    # ------------------------------------------------------------------ #
    # IMP-03: Permission class extraction                                  #
    # ------------------------------------------------------------------ #

    def _annotate_permission_metadata(self) -> None:
        """Write permission_classes metadata onto every VERTEX node."""
        for node in self.graph["nodes"]:
            if node["type"] != "VERTEX":
                continue
            nid = node["id"]
            perms = self._permissions.get(nid, [])
            node["metadata"]["permission_classes"] = perms
            # Convenience boolean flags readable by AI agents at a glance
            node["metadata"]["requires_auth"] = any(
                p in perms for p in ("IsAuthenticated", "IsAuthenticatedOrReadOnly")
            )
            node["metadata"]["admin_only"] = "IsAdminUser" in perms

    def _extract_permission_classes(self, class_node: ast.ClassDef) -> List[str]:
        """
        Pull permission_classes = [...] assignments from a view class body.

        Handles both simple lists of Names and attribute lookups like
        permissions.IsAuthenticated.
        """
        for node in ast.walk(class_node):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "permission_classes":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        names = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Name):
                                names.append(elt.id)
                            elif isinstance(elt, ast.Attribute):
                                names.append(elt.attr)
                        return names
        return []

    def _calculate_metadata(self, node_id: str, node_type: str, file_name: str, 
                           **kwargs) -> Dict[str, Any]:
        """
        Calculate physics-inspired metadata for nodes.
        
        Args:
            node_id: Node identifier
            node_type: Type of node
            file_name: Source file name
            **kwargs: Additional properties
            
        Returns:
            Dictionary containing metadata for the node
        """
        metadata = {
            "mass": ComplexityDefaults.DEFAULT_MASS,
            "charge": ComplexityDefaults.DEFAULT_CHARGE,
            "spin": ComplexityDefaults.DEFAULT_SPIN,
            "energy": ComplexityDefaults.DEFAULT_ENERGY,
            "coupling": ComplexityDefaults.DEFAULT_COUPLING,
            "lifetime": ComplexityDefaults.DEFAULT_LIFETIME,
            "file": file_name,
            "lines": kwargs.get("lines", 0),
            "line_start": kwargs.get("line_start"),
            "line_end": kwargs.get("line_end")
        }
        
        # Calculate type-specific metadata
        if node_type == "VERTEX":
            metadata["mass"] = self._calculate_view_complexity(node_id, file_name)
            metadata["energy"] = ComplexityDefaults.VIEW_ENERGY
        elif node_type == "PARTICLE":
            metadata["mass"] = self._calculate_model_complexity(node_id, file_name)
            metadata["charge"] = ComplexityDefaults.MODEL_CHARGE
        elif node_type == "TRANSFORM":
            metadata["mass"] = ComplexityDefaults.TRANSFORM_MASS
            metadata["coupling"] = ComplexityDefaults.TRANSFORM_COUPLING
        elif node_type == "FRONTEND":
            metadata["mass"] = self._calculate_template_complexity(node_id, file_name)
        elif node_type == "JAVASCRIPT":
            metadata["mass"] = ComplexityDefaults.JAVASCRIPT_MASS
            metadata["energy"] = ComplexityDefaults.JAVASCRIPT_ENERGY
        elif node_type == "AJAX":
            metadata["energy"] = ComplexityDefaults.AJAX_ENERGY
            metadata["coupling"] = ComplexityDefaults.AJAX_COUPLING
        elif node_type == "MEDIATOR":
            metadata["mass"] = ComplexityDefaults.JAVASCRIPT_MASS
            metadata["energy"] = ComplexityDefaults.DEFAULT_ENERGY
        
        return metadata

    def _read_file_content(self, file_path: str) -> Optional[str]:
        """
        Read file content with caching and error handling.
        
        Args:
            file_path: Path to the file
            
        Returns:
            File content or None if reading fails
        """
        if file_path in self._file_content_cache:
            return self._file_content_cache[file_path]
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                self._file_content_cache[file_path] = content
                return content
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            return None

    def _count_non_empty_lines(self, content: str) -> int:
        """Count non-empty lines in content."""
        return len([line for line in content.split('\n') if line.strip()])

    def _calculate_view_complexity(self, view_name: str, file_name: str) -> float:
        """
        Calculate complexity mass for view classes.
        
        Args:
            view_name: Name of the view
            file_name: Source file name
            
        Returns:
            Complexity score between 0 and COMPLEXITY_MAX
        """
        content = self._read_file_content(file_name)
        if not content:
            return ComplexityDefaults.DEFAULT_MASS
        
        try:
            lines = self._count_non_empty_lines(content)
            complexity = min(lines / ComplexityDefaults.VIEW_BASE_COMPLEXITY_DIVISOR, 
                           ComplexityDefaults.COMPLEXITY_MAX)
            
            # Add complexity bonuses for view type
            view_patterns = {
                "CreateView": ComplexityDefaults.VIEW_CREATEVIEW_BONUS,
                "UpdateView": ComplexityDefaults.VIEW_UPDATEVIEW_BONUS,
                "ListView": ComplexityDefaults.VIEW_LISTVIEW_BONUS,
                "DetailView": ComplexityDefaults.VIEW_DETAILVIEW_BONUS,
            }
            
            for pattern, bonus in view_patterns.items():
                if pattern in view_name:
                    complexity += bonus
            
            return round(min(complexity, ComplexityDefaults.COMPLEXITY_MAX), 2)
        except Exception as e:
            logger.warning(f"Error calculating view complexity for {view_name}: {e}")
            return ComplexityDefaults.DEFAULT_MASS

    def _calculate_model_complexity(self, model_name: str, file_name: str) -> float:
        """
        Calculate complexity mass for model classes.
        
        Args:
            model_name: Name of the model
            file_name: Source file name
            
        Returns:
            Complexity score between 0 and COMPLEXITY_MAX
        """
        content = self._read_file_content(file_name)
        if not content:
            return ComplexityDefaults.DEFAULT_MASS
        
        try:
            field_count = content.count('models.')
            relationship_count = content.count('ForeignKey') + content.count('ManyToManyField')
            
            complexity = (ComplexityDefaults.MODEL_BASE + 
                         (field_count * ComplexityDefaults.MODEL_FIELD_WEIGHT) + 
                         (relationship_count * ComplexityDefaults.MODEL_RELATION_WEIGHT))
            
            return round(min(complexity, ComplexityDefaults.COMPLEXITY_MAX), 2)
        except Exception as e:
            logger.warning(f"Error calculating model complexity for {model_name}: {e}")
            return ComplexityDefaults.DEFAULT_MASS

    def _calculate_template_complexity(self, template_name: str, file_name: str) -> float:
        """
        Calculate complexity mass for templates.
        
        Args:
            template_name: Name of the template
            file_name: Source file name
            
        Returns:
            Complexity score between 0 and COMPLEXITY_MAX
        """
        content = self._read_file_content(file_name)
        if not content:
            return ComplexityDefaults.TEMPLATE_DEFAULT
        
        try:
            var_count = len(RegexPatterns.TEMPLATE_VARIABLES.findall(content))
            tag_count = len(RegexPatterns.TEMPLATE_TAGS.findall(content))
            js_count = len(RegexPatterns.JS_FUNCTIONS.findall(content))
            
            complexity = (ComplexityDefaults.TEMPLATE_BASE +
                         (var_count * ComplexityDefaults.TEMPLATE_VAR_WEIGHT) +
                         (tag_count * ComplexityDefaults.TEMPLATE_TAG_WEIGHT) +
                         (js_count * ComplexityDefaults.TEMPLATE_JS_WEIGHT))
            
            return round(min(complexity, ComplexityDefaults.COMPLEXITY_MAX), 2)
        except Exception as e:
            logger.warning(f"Error calculating template complexity for {template_name}: {e}")
            return ComplexityDefaults.TEMPLATE_DEFAULT

    def _parse_code(self, path: Path) -> None:
        """
        Parse Python code file and extract components.
        
        Args:
            path: Path to the Python file
        """
        content = self._read_file_content(str(path))
        if not content:
            return
        
        try:
            tree = ast.parse(content)
            self._process_ast_nodes(tree, path)
        except SyntaxError as e:
            logger.warning(f"Syntax error parsing {path}: {e}")
        except Exception as e:
            logger.error(f"Error parsing code file {path}: {e}")

    def _process_ast_nodes(self, tree: ast.AST, path: Path) -> None:
        """
        Process AST nodes to extract components.
        
        Args:
            tree: AST tree to process
            path: Source file path
        """
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._process_class_node(node, path)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._process_function_node(node, path)

    def _process_class_node(self, node: ast.ClassDef, path: Path) -> None:
        """Process a class definition node."""
        current_class = node.name
        
        # Detect Models (Particles)
        if self._matches_pattern(node, self.config.get_model_detection_rules()):
            self._add_node(node.name, "PARTICLE", str(path), line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno))
        
        # Detect Views (Vertices)
        if self._matches_pattern(node, self.config.get_view_detection_rules()):
            self._add_node(node.name, "VERTEX", str(path), line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno))
            # IMP-03: capture permission_classes at parse time for later annotation
            self._permissions[node.name] = self._extract_permission_classes(node)
        
        # Detect Serializers (Transforms)
        if self._matches_pattern(node, self.config.get_serializer_detection_rules()):
            self._add_node(node.name, "TRANSFORM", str(path), line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno))
        
        if current_class not in self.node_ids:
            self._add_node(current_class, "MEDIATOR", str(path), line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno))

        # Process class body for relationships and nested interaction chains.
        self._process_class_assignments(node, current_class, path)
        self._process_callable_body(node, current_class, path)

    def _process_class_assignments(self, class_node: ast.ClassDef, 
                                   current_class: str, path: Path) -> None:
        """Extract model and serializer assignments from class body."""
        for child in ast.walk(class_node):
            if not isinstance(child, ast.Assign):
                continue
            
            for target in child.targets:
                if not isinstance(target, ast.Name):
                    continue
                
                if target.id == "model" and isinstance(child.value, ast.Name):
                    self._add_model_relationship(current_class, child.value.id, path)
                elif target.id == "serializer_class" and isinstance(child.value, ast.Name):
                    self._add_serializer_relationship(current_class, child.value.id, path)

    def _add_model_relationship(self, source: str, model_name: str, path: Path) -> None:
        """Add model relationship edge."""
        self._add_node(model_name, "PARTICLE", str(path), imported=True)
        self._add_edge(source, model_name, "PARTICLE_ENTANGLEMENT")

    def _add_serializer_relationship(self, source: str, serializer_name: str, path: Path) -> None:
        """Add serializer relationship edge."""
        self._add_node(serializer_name, "TRANSFORM", str(path), imported=True)
        self._add_edge(source, serializer_name, "SERIALIZER_ENTANGLEMENT")

    def _process_function_node(self, node: ast.FunctionDef, path: Path) -> None:
        """Process a function definition node."""
        node_type = "VERTEX" if self._matches_function_pattern(node, self.config.get_view_detection_rules()) else "MEDIATOR"
        self._add_node(node.name, node_type, str(path), line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno))
        self._process_callable_body(node, node.name, path)

    def _process_callable_body(self, owner_node: ast.AST, source: str, path: Path) -> None:
        """Extract project-local calls and ORM touches from a callable/class body."""
        for child in ast.walk(owner_node):
            if child is owner_node or not isinstance(child, ast.Call):
                continue

            call_name = self._extract_call_name(child)
            # BUG-02 fix: skip Django/ORM builtins that would collapse into a
            # shared global mediator node and produce spurious cross-view edges.
            if call_name and call_name not in self.ORM_BUILTIN_SKIP and call_name != source:
                # IMP-01: prefer _symbol_to_file (cross-app import map) over
                # callable_defs (same-file scan) so that calls to functions
                # defined in other apps resolve to the correct source file.
                resolved_file = (
                    self._symbol_to_file.get(call_name)
                    or self.callable_defs.get(call_name)
                )
                if resolved_file:
                    self._add_node(call_name, "MEDIATOR", resolved_file, imported=True)
                    self._add_edge(source, call_name, "CALL")

            if isinstance(child.func, ast.Attribute):
                model_name = self._extract_orm_model_name(child)
                if model_name and self._matches_orm_pattern(ast.unparse(child)):
                    self._add_node(model_name, "PARTICLE", str(path), imported=True)
                    self._add_edge(source, model_name, "PARTICLE_ENTANGLEMENT")

    def _extract_call_name(self, call_node: ast.Call) -> Optional[str]:
        """Return the canonical project-local name from a call expression."""
        func = call_node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def _extract_orm_model_name(self, call_node: ast.Call) -> Optional[str]:
        """Extract the model name from supported ORM call shapes."""
        func = call_node.func
        if not isinstance(func, ast.Attribute):
            return None

        value = func.value
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute) and value.attr in {"objects", "query"} and isinstance(value.value, ast.Name):
            return value.value.id
        return None

    def _parse_template(self, path: Path) -> None:
        """
        Parse template file and extract components.
        
        Args:
            path: Path to the template file
        """
        content = self._read_file_content(str(path))
        if not content:
            return
        
        try:
            template_name = path.stem
            line_count = len(content.splitlines()) or 1
            self._add_node(template_name, "FRONTEND", str(path), line_start=1, line_end=line_count)
            
            template_patterns = self.config.get_template_patterns()
            if template_patterns:
                self._process_template_patterns(content, template_name, path, template_patterns)
            
            self._process_template_dependencies(content, template_name, path)
        except Exception as e:
            logger.error(f"Error parsing template {path}: {e}")

    def _process_template_patterns(self, content: str, template_name: str, 
                                   path: Path, patterns: Dict[str, str]) -> None:
        """Process template patterns."""
        pattern_handlers = {
            "variables": self._process_template_variables,
            "js_functions": self._process_js_functions,
            "arrow_functions": self._process_arrow_functions,
            "fetch_calls": self._process_fetch_calls,
            "async_functions": self._process_async_functions,
            "event_listeners": self._process_event_listeners,
        }
        
        for pattern_key, handler in pattern_handlers.items():
            if pattern_key in patterns:
                handler(content, template_name, path, patterns[pattern_key])

    def _process_template_variables(self, content: str, template_name: str, 
                                    path: Path, pattern: str) -> None:
        """Process template variables."""
        variables = re.findall(pattern, content)
        for var in variables:
            var_root = var.split('.')[0]
            self._add_edge(template_name, var_root, "OBSERVATION")

    def _process_js_functions(self, content: str, template_name: str, 
                              path: Path, pattern: str) -> None:
        """Process JavaScript functions."""
        functions = re.findall(pattern, content)
        for func in functions:
            self._add_node(func, "JAVASCRIPT", str(path))
            self._add_edge(template_name, func, "EVENT")

    def _process_arrow_functions(self, content: str, template_name: str, 
                                 path: Path, pattern: str) -> None:
        """Process arrow functions and event handlers."""
        functions = re.findall(pattern, content)
        for func in functions:
            if func not in self.GLOBAL_JS_OBJECTS:
                self._add_node(func, "JAVASCRIPT", str(path))
                self._add_edge(template_name, func, "EVENT")

    def _process_fetch_calls(self, content: str, template_name: str, 
                             path: Path, pattern: str) -> None:
        """Process AJAX/fetch calls."""
        fetch_calls = re.findall(pattern, content)
        for endpoint in fetch_calls:
            self._add_node(endpoint, "AJAX", str(path))
            self._add_edge(template_name, endpoint, "AJAX")

    def _process_async_functions(self, content: str, template_name: str, 
                                 path: Path, pattern: str) -> None:
        """Process async/await patterns."""
        functions = re.findall(pattern, content)
        for func in functions:
            self._add_node(func, "JAVASCRIPT", str(path))
            self._add_edge(template_name, func, "VIRTUAL")

    def _process_event_listeners(self, content: str, template_name: str, 
                                 path: Path, pattern: str) -> None:
        """Process event listeners."""
        listeners = re.findall(pattern, content)
        for event in listeners:
            self._add_node(f"{event}_handler", "EVENT", str(path))
            self._add_edge(template_name, f"{event}_handler", "EVENT")

    def _process_template_dependencies(self, content: str, template_name: str, path: Path) -> None:
        """Process external library dependencies in template."""
        dependencies = []
        
        if RegexPatterns.LEAFLET_MAP.search(content):
            dependencies.append('Leaflet')
        if RegexPatterns.JQUERY.search(content):
            dependencies.append('jQuery')
        if RegexPatterns.BOOTSTRAP.search(content):
            dependencies.append('Bootstrap')
        if RegexPatterns.AXIOS.search(content):
            dependencies.append('Axios')
        
        for dep in dependencies:
            self._add_node(dep, "DEPENDENCY", str(path))
            self._add_edge(template_name, dep, "DEPENDENCY")

    def _matches_pattern(self, node: ast.ClassDef, patterns: List[Dict[str, str]]) -> bool:
        """Check if AST node matches any of the given patterns."""
        for pattern in patterns:
            pattern_type = pattern.get("type")
            pattern_value = pattern.get("pattern")
            
            if pattern_type == "class_inheritance":
                if self._matches_inheritance(node, pattern_value):
                    return True
            elif pattern_type == "class_name_suffix":
                if self._matches_class_suffix(node, pattern_value):
                    return True
            elif pattern_type == "class_decoration":
                if self._matches_class_decorator(node, pattern_value):
                    return True
        
        return False

    def _matches_inheritance(self, node: ast.ClassDef, pattern: str) -> bool:
        """Check if class inherits from pattern."""
        for base in node.bases:
            try:
                if ast.unparse(base) == pattern:
                    return True
            except Exception:
                pass
            if hasattr(base, 'attr') and base.attr == pattern:
                return True
            elif hasattr(base, 'id') and base.id == pattern:
                return True
            elif (hasattr(base, 'value') and hasattr(base.value, 'id') and 
                  base.value.id == pattern):
                return True
        return False

    def _matches_class_suffix(self, node: ast.ClassDef, pattern: Any) -> bool:
        """Check if class name matches suffix pattern."""
        if isinstance(pattern, str):
            return node.name.endswith(pattern)
        elif isinstance(pattern, list):
            return any(node.name.endswith(suffix) for suffix in pattern)
        return False

    def _matches_class_decorator(self, node: ast.ClassDef, pattern: str) -> bool:
        """Check if class has matching decorator."""
        for decorator in node.decorator_list:
            if hasattr(decorator, 'attr') and decorator.attr == pattern:
                return True
            elif hasattr(decorator, 'id') and decorator.id == pattern:
                return True
        return False

    def _matches_function_pattern(self, node: ast.FunctionDef, patterns: List[Dict[str, str]]) -> bool:
        """Check if function matches any of the given patterns."""
        for pattern in patterns:
            pattern_type = pattern.get("type")
            pattern_value = pattern.get("pattern")
            
            if pattern_type == "function_decorator":
                if self._matches_function_decorator(node, pattern_value):
                    return True
            elif pattern_type == "function_name_contains":
                if self._matches_function_name(node, pattern_value):
                    return True
        
        return False

    def _matches_function_decorator(self, node: ast.FunctionDef, pattern: str) -> bool:
        """Check if function has matching decorator."""
        for decorator in node.decorator_list:
            if hasattr(decorator, 'attr') and decorator.attr.startswith(pattern):
                return True
            elif hasattr(decorator, 'id') and decorator.id.startswith(pattern):
                return True
        return False

    def _matches_function_name(self, node: ast.FunctionDef, pattern: Any) -> bool:
        """Check if function name matches pattern."""
        if isinstance(pattern, str):
            return pattern in node.name.lower()
        elif isinstance(pattern, list):
            return any(p in node.name.lower() for p in pattern)
        return False

    def _matches_orm_pattern(self, code_str: str) -> bool:
        """Check if code string matches any ORM patterns."""
        for pattern in self.config.get_orm_patterns():
            if re.search(pattern, code_str):
                return True
        return False
