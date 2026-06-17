import ast
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .config import get_framework_config
    from .node_identity import NodeIdentity
except ImportError:
    from config import get_framework_config
    from node_identity import NodeIdentity

logger = logging.getLogger(__name__)


class ComplexityDefaults:
    DEFAULT_MASS = 1.0
    DEFAULT_CHARGE = 1.0
    DEFAULT_SPIN = 0.5
    DEFAULT_ENERGY = 0.5
    DEFAULT_COUPLING = 0.5
    DEFAULT_LIFETIME = 1.0
    COMPLEXITY_MAX = 2.0
    VIEW_CREATEVIEW_BONUS = 0.3
    VIEW_UPDATEVIEW_BONUS = 0.2
    VIEW_LISTVIEW_BONUS = 0.1
    VIEW_DETAILVIEW_BONUS = 0.1
    VIEW_BASE_COMPLEXITY_DIVISOR = 100.0
    VIEW_ENERGY = 0.8
    MODEL_BASE = 0.5
    MODEL_FIELD_WEIGHT = 0.1
    MODEL_RELATION_WEIGHT = 0.2
    MODEL_CHARGE = 1.2
    TRANSFORM_MASS = 0.6
    TRANSFORM_COUPLING = 0.8
    JAVASCRIPT_MASS = 0.3
    JAVASCRIPT_ENERGY = 0.9
    AJAX_ENERGY = 1.0
    AJAX_COUPLING = 0.7
    TEMPLATE_BASE = 0.3
    TEMPLATE_VAR_WEIGHT = 0.05
    TEMPLATE_TAG_WEIGHT = 0.1
    TEMPLATE_JS_WEIGHT = 0.15
    TEMPLATE_DEFAULT = 0.5


class RegexPatterns:
    TEMPLATE_VARIABLES = re.compile(r"{{\s*[\w\.]+\s*}}")
    TEMPLATE_TAGS = re.compile(r"{%\s*[^%]+\s*%}")
    JS_FUNCTIONS = re.compile(r"function\s+\w+")
    LEAFLET_MAP = re.compile(r"L\.(map|marker)\(")
    JQUERY = re.compile(r"\$\(|jQuery")
    BOOTSTRAP = re.compile(r"bootstrap", re.IGNORECASE)
    AXIOS = re.compile(r"axios")


class FeynExtractor:
    """Extract framework components and build a dependency graph."""

    GLOBAL_JS_OBJECTS = {"console", "document", "window", "navigator"}

    def __init__(self, project_path: str, framework: str = "auto") -> None:
        self.project_path = Path(project_path).resolve()
        if not self.project_path.exists():
            raise ValueError(f"Project path does not exist: {self.project_path}")

        self.config = get_framework_config(framework)
        self.identities = NodeIdentity(self.project_path)
        self.graph: Dict[str, List[Any]] = {"nodes": [], "edges": []}
        self.node_ids: Set[str] = set()
        self._nodes_by_id: Dict[str, Dict[str, Any]] = {}
        self._edge_ids: Set[Tuple[str, str, str]] = set()
        self._file_content_cache: Dict[str, str] = {}
        self.callable_defs: Dict[str, List[Dict[str, str]]] = {}
        self.class_defs: Dict[str, List[Dict[str, str]]] = {}

    def scan(self) -> Dict[str, List[Any]]:
        excluded = set(self.config.exclude_dirs)
        code_extensions = tuple(self.config.code_extensions)
        template_extensions = tuple(self.config.template_extensions)
        code_paths: List[Path] = []
        template_paths: List[Path] = []

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [directory for directory in dirs if directory not in excluded]
            for filename in files:
                path = Path(root) / filename
                if filename.endswith(code_extensions):
                    code_paths.append(path)
                elif filename.endswith(template_extensions):
                    template_paths.append(path)

        self._collect_definitions(code_paths)
        for path in code_paths:
            self._parse_code(path)
        for path in template_paths:
            self._parse_template(path)
        return self.graph

    def _add_node(
        self,
        node_id: str,
        node_type: str,
        file_name: str,
        *,
        name: Optional[str] = None,
        qualified_name: Optional[str] = None,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        display_name = name or node_id.rsplit(".", 1)[-1]
        node_data = {
            "id": node_id,
            "name": display_name,
            "qualified_name": qualified_name or display_name,
            "type": node_type,
            "language": language,
            "file": file_name,
            "metadata": self._calculate_metadata(display_name, node_type, file_name, **kwargs),
        }
        node_data.update(kwargs)

        existing = self._nodes_by_id.get(node_id)
        if existing is None:
            self.node_ids.add(node_id)
            self._nodes_by_id[node_id] = node_data
            self.graph["nodes"].append(node_data)
            return

        if not kwargs.get("imported") and existing.get("imported"):
            existing.clear()
            existing.update(node_data)
            existing.pop("imported", None)

    def _add_edge(self, source: str, target: str, edge_type: str, **kwargs: Any) -> None:
        edge_key = (source, target, edge_type)
        if edge_key in self._edge_ids:
            return
        self._edge_ids.add(edge_key)
        edge = {"source": source, "target": target, "type": edge_type}
        edge.update(kwargs)
        self.graph["edges"].append(edge)

    def _collect_definitions(self, paths: List[Path]) -> None:
        for path in paths:
            content = self._read_file_content(str(path))
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError as exc:
                logger.warning("Syntax error parsing %s: %s", path, exc)
                continue

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    class_id = self.identities.python(node.name, path)
                    self._register_definition(self.class_defs, node.name, class_id, path)
                    self._register_definition(self.callable_defs, node.name, class_id, path)
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_id = self.identities.python(child.name, path, node.name)
                            self._register_definition(
                                self.callable_defs, child.name, method_id, path, parent=node.name
                            )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_id = self.identities.python(node.name, path)
                    self._register_definition(self.callable_defs, node.name, function_id, path)

    def _register_definition(
        self,
        index: Dict[str, List[Dict[str, str]]],
        name: str,
        node_id: str,
        path: Path,
        parent: Optional[str] = None,
    ) -> None:
        index.setdefault(name, []).append(
            {"id": node_id, "path": str(path.resolve()), "parent": parent or ""}
        )

    def _resolve_definition(
        self,
        index: Dict[str, List[Dict[str, str]]],
        name: str,
        path: Path,
        parent: Optional[str] = None,
    ) -> Optional[str]:
        candidates = index.get(name, [])
        if parent:
            parent_matches = [item for item in candidates if item["parent"] == parent]
            if len(parent_matches) == 1:
                return parent_matches[0]["id"]
        same_file = [item for item in candidates if item["path"] == str(path.resolve())]
        if len(same_file) == 1:
            return same_file[0]["id"]
        if len(candidates) == 1:
            return candidates[0]["id"]
        return None

    def _calculate_metadata(
        self, node_name: str, node_type: str, file_name: str, **kwargs: Any
    ) -> Dict[str, Any]:
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
            "line_end": kwargs.get("line_end"),
        }
        if node_type == "VERTEX":
            metadata["mass"] = self._calculate_view_complexity(node_name, file_name)
            metadata["energy"] = ComplexityDefaults.VIEW_ENERGY
        elif node_type == "PARTICLE":
            metadata["mass"] = self._calculate_model_complexity(node_name, file_name)
            metadata["charge"] = ComplexityDefaults.MODEL_CHARGE
        elif node_type == "TRANSFORM":
            metadata["mass"] = ComplexityDefaults.TRANSFORM_MASS
            metadata["coupling"] = ComplexityDefaults.TRANSFORM_COUPLING
        elif node_type == "FRONTEND":
            metadata["mass"] = self._calculate_template_complexity(node_name, file_name)
        elif node_type in {"JAVASCRIPT", "MEDIATOR"}:
            metadata["mass"] = ComplexityDefaults.JAVASCRIPT_MASS
        elif node_type == "AJAX":
            metadata["energy"] = ComplexityDefaults.AJAX_ENERGY
            metadata["coupling"] = ComplexityDefaults.AJAX_COUPLING
        return metadata

    def _read_file_content(self, file_path: str) -> Optional[str]:
        if file_path in self._file_content_cache:
            return self._file_content_cache[file_path]
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read file %s: %s", file_path, exc)
            return None
        self._file_content_cache[file_path] = content
        return content

    def _calculate_view_complexity(self, view_name: str, file_name: str) -> float:
        content = self._read_file_content(file_name)
        if not content:
            return ComplexityDefaults.DEFAULT_MASS
        complexity = min(
            len([line for line in content.splitlines() if line.strip()])
            / ComplexityDefaults.VIEW_BASE_COMPLEXITY_DIVISOR,
            ComplexityDefaults.COMPLEXITY_MAX,
        )
        bonuses = {
            "CreateView": ComplexityDefaults.VIEW_CREATEVIEW_BONUS,
            "UpdateView": ComplexityDefaults.VIEW_UPDATEVIEW_BONUS,
            "ListView": ComplexityDefaults.VIEW_LISTVIEW_BONUS,
            "DetailView": ComplexityDefaults.VIEW_DETAILVIEW_BONUS,
        }
        complexity += sum(value for key, value in bonuses.items() if key in view_name)
        return round(min(complexity, ComplexityDefaults.COMPLEXITY_MAX), 2)

    def _calculate_model_complexity(self, model_name: str, file_name: str) -> float:
        content = self._read_file_content(file_name)
        if not content:
            return ComplexityDefaults.DEFAULT_MASS
        field_count = content.count("models.")
        relationship_count = content.count("ForeignKey") + content.count("ManyToManyField")
        value = (
            ComplexityDefaults.MODEL_BASE
            + field_count * ComplexityDefaults.MODEL_FIELD_WEIGHT
            + relationship_count * ComplexityDefaults.MODEL_RELATION_WEIGHT
        )
        return round(min(value, ComplexityDefaults.COMPLEXITY_MAX), 2)

    def _calculate_template_complexity(self, template_name: str, file_name: str) -> float:
        content = self._read_file_content(file_name)
        if not content:
            return ComplexityDefaults.TEMPLATE_DEFAULT
        value = (
            ComplexityDefaults.TEMPLATE_BASE
            + len(RegexPatterns.TEMPLATE_VARIABLES.findall(content))
            * ComplexityDefaults.TEMPLATE_VAR_WEIGHT
            + len(RegexPatterns.TEMPLATE_TAGS.findall(content))
            * ComplexityDefaults.TEMPLATE_TAG_WEIGHT
            + len(RegexPatterns.JS_FUNCTIONS.findall(content))
            * ComplexityDefaults.TEMPLATE_JS_WEIGHT
        )
        return round(min(value, ComplexityDefaults.COMPLEXITY_MAX), 2)

    def _parse_code(self, path: Path) -> None:
        content = self._read_file_content(str(path))
        if not content:
            return
        try:
            self._process_ast_nodes(ast.parse(content), path)
        except SyntaxError as exc:
            logger.warning("Syntax error parsing %s: %s", path, exc)
        except Exception as exc:
            logger.error("Error parsing code file %s: %s", path, exc)

    def _process_ast_nodes(self, tree: ast.AST, path: Path) -> None:
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._process_class_node(node, path)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._process_function_node(node, path)

    def _process_class_node(self, node: ast.ClassDef, path: Path) -> None:
        class_id = self.identities.python(node.name, path)
        node_type = "MEDIATOR"
        if self._matches_pattern(node, self.config.get_model_detection_rules()):
            node_type = "PARTICLE"
        elif self._matches_pattern(node, self.config.get_view_detection_rules()):
            node_type = "VERTEX"
        elif self._matches_pattern(node, self.config.get_serializer_detection_rules()):
            node_type = "TRANSFORM"

        self._add_node(
            class_id,
            node_type,
            str(path),
            name=node.name,
            qualified_name=f"{self.identities.module_name(path)}.{node.name}",
            language="python",
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
        )
        self._process_class_assignments(node, class_id, path)
        self._process_callable_body(node, class_id, path, parent=node.name)

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_id = self.identities.python(child.name, path, node.name)
                self._add_node(
                    method_id,
                    "MEDIATOR",
                    str(path),
                    name=child.name,
                    qualified_name=(
                        f"{self.identities.module_name(path)}.{node.name}.{child.name}"
                    ),
                    language="python",
                    line_start=child.lineno,
                    line_end=getattr(child, "end_lineno", child.lineno),
                )
                self._add_edge(class_id, method_id, "CONTAINS")
                self._process_callable_body(child, method_id, path, parent=node.name)

    def _process_class_assignments(self, class_node: ast.ClassDef, source_id: str, path: Path) -> None:
        for child in class_node.body:
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if not isinstance(target, ast.Name) or not isinstance(child.value, ast.Name):
                    continue
                if target.id == "model":
                    self._add_named_relationship(
                        source_id, child.value.id, path, "PARTICLE", "PARTICLE_ENTANGLEMENT"
                    )
                elif target.id == "serializer_class":
                    self._add_named_relationship(
                        source_id, child.value.id, path, "TRANSFORM", "SERIALIZER_ENTANGLEMENT"
                    )

    def _add_named_relationship(
        self,
        source: str,
        target_name: str,
        path: Path,
        node_type: str,
        edge_type: str,
    ) -> None:
        target_id = self._resolve_definition(self.class_defs, target_name, path)
        if target_id is None:
            target_id = NodeIdentity.unresolved(node_type.lower(), target_name)
        self._add_node(
            target_id,
            node_type,
            str(path),
            name=target_name,
            qualified_name=target_name,
            language="python",
            imported=True,
        )
        self._add_edge(source, target_id, edge_type)

    def _process_function_node(self, node: ast.AST, path: Path) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        node_id = self.identities.python(node.name, path)
        node_type = (
            "VERTEX"
            if self._matches_function_pattern(node, self.config.get_view_detection_rules())
            else "MEDIATOR"
        )
        self._add_node(
            node_id,
            node_type,
            str(path),
            name=node.name,
            qualified_name=f"{self.identities.module_name(path)}.{node.name}",
            language="python",
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
        )
        self._process_callable_body(node, node_id, path)

    def _process_callable_body(
        self, owner_node: ast.AST, source_id: str, path: Path, parent: Optional[str] = None
    ) -> None:
        for child in ast.walk(owner_node):
            if child is owner_node or not isinstance(child, ast.Call):
                continue
            call_name = self._extract_call_name(child)
            if call_name:
                method_parent = parent if self._is_self_call(child) else None
                target_id = self._resolve_definition(
                    self.callable_defs, call_name, path, parent=method_parent
                )
                if target_id and target_id != source_id:
                    self._add_edge(source_id, target_id, "CALL")

            if isinstance(child.func, ast.Attribute):
                model_name = self._extract_orm_model_name(child)
                if model_name and self._matches_orm_pattern(ast.unparse(child)):
                    self._add_named_relationship(
                        source_id, model_name, path, "PARTICLE", "PARTICLE_ENTANGLEMENT"
                    )

    @staticmethod
    def _extract_call_name(call_node: ast.Call) -> Optional[str]:
        if isinstance(call_node.func, ast.Name):
            return call_node.func.id
        if isinstance(call_node.func, ast.Attribute):
            return call_node.func.attr
        return None

    @staticmethod
    def _is_self_call(call_node: ast.Call) -> bool:
        return (
            isinstance(call_node.func, ast.Attribute)
            and isinstance(call_node.func.value, ast.Name)
            and call_node.func.value.id in {"self", "cls"}
        )

    @staticmethod
    def _extract_orm_model_name(call_node: ast.Call) -> Optional[str]:
        func = call_node.func
        if not isinstance(func, ast.Attribute):
            return None
        value = func.value
        if isinstance(value, ast.Name):
            return value.id
        if (
            isinstance(value, ast.Attribute)
            and value.attr in {"objects", "query"}
            and isinstance(value.value, ast.Name)
        ):
            return value.value.id
        return None

    def _parse_template(self, path: Path) -> None:
        content = self._read_file_content(str(path))
        if not content:
            return
        template_id = self.identities.template(path)
        relative = self.identities.relative_path(path)
        self._add_node(
            template_id,
            "FRONTEND",
            str(path),
            name=path.name,
            qualified_name=relative,
            language="template",
            line_start=1,
            line_end=len(content.splitlines()) or 1,
        )
        patterns = self.config.get_template_patterns()
        if patterns:
            self._process_template_patterns(content, template_id, path, patterns)
        self._process_template_dependencies(content, template_id, path)

    def _process_template_patterns(
        self, content: str, template_id: str, path: Path, patterns: Dict[str, str]
    ) -> None:
        handlers = {
            "variables": self._process_template_variables,
            "js_functions": self._process_js_functions,
            "arrow_functions": self._process_arrow_functions,
            "fetch_calls": self._process_fetch_calls,
            "async_functions": self._process_async_functions,
            "event_listeners": self._process_event_listeners,
        }
        for key, handler in handlers.items():
            if key in patterns:
                handler(content, template_id, path, patterns[key])

    def _process_template_variables(self, content: str, template_id: str, path: Path, pattern: str) -> None:
        for variable in re.findall(pattern, content):
            root = variable.split(".")[0]
            symbol_id = self.identities.template_symbol(path, root)
            self._add_node(
                symbol_id,
                "OBSERVATION",
                str(path),
                name=root,
                qualified_name=f"{self.identities.relative_path(path)}::{root}",
                language="template",
            )
            self._add_edge(template_id, symbol_id, "OBSERVATION")

    def _add_javascript_node(self, template_id: str, path: Path, name: str, edge_type: str) -> None:
        node_id = self.identities.javascript(path, name)
        self._add_node(
            node_id,
            "JAVASCRIPT",
            str(path),
            name=name,
            qualified_name=f"{self.identities.relative_path(path)}::{name}",
            language="javascript",
        )
        self._add_edge(template_id, node_id, edge_type)

    def _process_js_functions(self, content: str, template_id: str, path: Path, pattern: str) -> None:
        for name in re.findall(pattern, content):
            self._add_javascript_node(template_id, path, name, "EVENT")

    def _process_arrow_functions(self, content: str, template_id: str, path: Path, pattern: str) -> None:
        for name in re.findall(pattern, content):
            if name not in self.GLOBAL_JS_OBJECTS:
                self._add_javascript_node(template_id, path, name, "EVENT")

    def _process_fetch_calls(self, content: str, template_id: str, path: Path, pattern: str) -> None:
        for endpoint in re.findall(pattern, content):
            node_id = NodeIdentity.ajax(endpoint)
            self._add_node(node_id, "AJAX", str(path), name=endpoint, qualified_name=endpoint)
            self._add_edge(template_id, node_id, "AJAX")

    def _process_async_functions(self, content: str, template_id: str, path: Path, pattern: str) -> None:
        for name in re.findall(pattern, content):
            self._add_javascript_node(template_id, path, name, "VIRTUAL")

    def _process_event_listeners(self, content: str, template_id: str, path: Path, pattern: str) -> None:
        for event in re.findall(pattern, content):
            self._add_javascript_node(template_id, path, f"{event}_handler", "EVENT")

    def _process_template_dependencies(self, content: str, template_id: str, path: Path) -> None:
        dependencies = []
        if RegexPatterns.LEAFLET_MAP.search(content):
            dependencies.append("Leaflet")
        if RegexPatterns.JQUERY.search(content):
            dependencies.append("jQuery")
        if RegexPatterns.BOOTSTRAP.search(content):
            dependencies.append("Bootstrap")
        if RegexPatterns.AXIOS.search(content):
            dependencies.append("Axios")
        for name in dependencies:
            node_id = NodeIdentity.dependency(name)
            self._add_node(node_id, "DEPENDENCY", str(path), name=name, qualified_name=name)
            self._add_edge(template_id, node_id, "DEPENDENCY")

    def _matches_pattern(self, node: ast.ClassDef, patterns: List[Dict[str, Any]]) -> bool:
        for pattern in patterns:
            kind = pattern.get("type")
            value = pattern.get("pattern")
            if kind == "class_inheritance" and self._matches_inheritance(node, value):
                return True
            if kind == "class_name_suffix" and self._matches_class_suffix(node, value):
                return True
            if kind == "class_decoration" and self._matches_class_decorator(node, value):
                return True
        return False

    @staticmethod
    def _matches_inheritance(node: ast.ClassDef, pattern: str) -> bool:
        for base in node.bases:
            try:
                rendered = ast.unparse(base)
            except Exception:
                continue
            if rendered == pattern or rendered.endswith(f".{pattern}"):
                return True
        return False

    @staticmethod
    def _matches_class_suffix(node: ast.ClassDef, pattern: Any) -> bool:
        if isinstance(pattern, str):
            return node.name.endswith(pattern)
        if isinstance(pattern, list):
            return any(node.name.endswith(suffix) for suffix in pattern)
        return False

    @staticmethod
    def _matches_class_decorator(node: ast.ClassDef, pattern: str) -> bool:
        return any(ast.unparse(item).startswith(pattern) for item in node.decorator_list)

    def _matches_function_pattern(self, node: ast.AST, patterns: List[Dict[str, Any]]) -> bool:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for pattern in patterns:
            kind = pattern.get("type")
            value = pattern.get("pattern")
            if kind == "function_decorator" and self._matches_function_decorator(node, value):
                return True
            if kind == "function_name_contains" and self._matches_function_name(node, value):
                return True
        return False

    @staticmethod
    def _matches_function_decorator(node: ast.AST, pattern: str) -> bool:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        normalized = pattern.lstrip("@")
        return any(ast.unparse(item).startswith(normalized) for item in node.decorator_list)

    @staticmethod
    def _matches_function_name(node: ast.AST, pattern: Any) -> bool:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        lowered = node.name.lower()
        if isinstance(pattern, str):
            return pattern.lower() in lowered
        if isinstance(pattern, list):
            return any(item.lower() in lowered for item in pattern)
        return False

    def _matches_orm_pattern(self, code_str: str) -> bool:
        return any(re.search(pattern, code_str) for pattern in self.config.get_orm_patterns())
