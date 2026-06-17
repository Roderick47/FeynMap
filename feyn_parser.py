import ast
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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


class ScopedCallCollector(ast.NodeVisitor):
    """Collect calls and assignments without entering nested callable scopes."""

    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.calls: List[ast.Call] = []
        self.assignments: List[ast.AST] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.assignments.append(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.assignments.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        if node is self.root:
            self.visit(node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


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

        self.definitions_by_name: Dict[str, List[Dict[str, str]]] = {}
        self.definitions_by_qualified_name: Dict[str, Dict[str, str]] = {}
        self.imports_by_file: Dict[str, Dict[str, Dict[str, str]]] = {}
        self.modules_by_file: Dict[str, str] = {}

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

        self._collect_project_symbols(code_paths)
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

    def _collect_project_symbols(self, paths: List[Path]) -> None:
        for path in paths:
            resolved_path = str(path.resolve())
            module = self.identities.module_name(path)
            self.modules_by_file[resolved_path] = module
            content = self._read_file_content(resolved_path)
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError as exc:
                logger.warning("Syntax error parsing %s: %s", path, exc)
                continue

            self.imports_by_file[resolved_path] = self._collect_imports(tree, module)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    self._register_definition(node.name, path, "class")
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self._register_definition(child.name, path, "method", parent=node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._register_definition(node.name, path, "function")

    def _register_definition(
        self, name: str, path: Path, kind: str, parent: Optional[str] = None
    ) -> None:
        module = self.identities.module_name(path)
        qualified_name = ".".join(part for part in (module, parent, name) if part)
        node_id = self.identities.python(name, path, parent)
        definition = {
            "id": node_id,
            "name": name,
            "module": module,
            "parent": parent or "",
            "path": str(path.resolve()),
            "kind": kind,
            "qualified_name": qualified_name,
        }
        self.definitions_by_name.setdefault(name, []).append(definition)
        self.definitions_by_qualified_name[qualified_name] = definition

    def _collect_imports(self, tree: ast.AST, current_module: str) -> Dict[str, Dict[str, str]]:
        imports: Dict[str, Dict[str, str]] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".")[0]
                    imports[local_name] = {"kind": "module", "module": alias.name}
            elif isinstance(node, ast.ImportFrom):
                module = self._resolve_import_module(current_module, node.module or "", node.level)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local_name = alias.asname or alias.name
                    imports[local_name] = {
                        "kind": "symbol",
                        "module": module,
                        "symbol": alias.name,
                    }
        return imports

    @staticmethod
    def _resolve_import_module(current_module: str, imported_module: str, level: int) -> str:
        if level <= 0:
            return imported_module
        package_parts = current_module.split(".")[:-1]
        keep = max(0, len(package_parts) - (level - 1))
        base = package_parts[:keep]
        if imported_module:
            base.extend(imported_module.split("."))
        return ".".join(base)

    def _definition_by_qualified_name(self, qualified_name: str) -> Optional[Dict[str, str]]:
        return self.definitions_by_qualified_name.get(qualified_name)

    def _same_file_definition(
        self, name: str, path: Path, kind: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        matches = [
            item
            for item in self.definitions_by_name.get(name, [])
            if item["path"] == str(path.resolve())
            and not item["parent"]
            and (kind is None or item["kind"] == kind)
        ]
        return matches[0] if len(matches) == 1 else None

    def _resolve_name_reference(self, name: str, path: Path) -> Optional[Dict[str, str]]:
        same_file = self._same_file_definition(name, path)
        if same_file:
            return same_file

        import_info = self.imports_by_file.get(str(path.resolve()), {}).get(name)
        if import_info and import_info["kind"] == "symbol":
            return self._definition_by_qualified_name(
                f"{import_info['module']}.{import_info['symbol']}"
            )

        candidates = self.definitions_by_name.get(name, [])
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_class_reference(self, expression: ast.AST, path: Path) -> Optional[Dict[str, str]]:
        if isinstance(expression, ast.Name):
            definition = self._resolve_name_reference(expression.id, path)
            return definition if definition and definition["kind"] == "class" else None
        if isinstance(expression, ast.Attribute):
            qualified = self._qualified_expression(expression, path)
            definition = self._definition_by_qualified_name(qualified) if qualified else None
            return definition if definition and definition["kind"] == "class" else None
        return None

    def _qualified_expression(self, expression: ast.AST, path: Path) -> Optional[str]:
        parts = self._attribute_parts(expression)
        if not parts:
            return None
        imports = self.imports_by_file.get(str(path.resolve()), {})
        root = parts[0]
        import_info = imports.get(root)
        if import_info:
            if import_info["kind"] == "module":
                return ".".join([import_info["module"]] + parts[1:])
            return ".".join(
                [import_info["module"], import_info["symbol"]] + parts[1:]
            )
        return ".".join(parts)

    @staticmethod
    def _attribute_parts(expression: ast.AST) -> List[str]:
        if isinstance(expression, ast.Name):
            return [expression.id]
        if isinstance(expression, ast.Attribute):
            return FeynExtractor._attribute_parts(expression.value) + [expression.attr]
        return []

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

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_id = self.identities.python(child.name, path, node.name)
                self._add_node(
                    method_id,
                    "MEDIATOR",
                    str(path),
                    name=child.name,
                    qualified_name=f"{self.identities.module_name(path)}.{node.name}.{child.name}",
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
        definition = self._resolve_name_reference(target_name, path)
        target_id = definition["id"] if definition else NodeIdentity.unresolved(node_type.lower(), target_name)
        self._add_node(
            target_id,
            node_type,
            definition["path"] if definition else str(path),
            name=target_name,
            qualified_name=definition["qualified_name"] if definition else target_name,
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
        collector = ScopedCallCollector(owner_node)
        collector.visit(owner_node)
        local_types = self._infer_local_types(owner_node, collector.assignments, path)

        for call in collector.calls:
            resolved = self._resolve_call(call, path, parent, local_types)
            if resolved and resolved["id"] != source_id:
                self._add_edge(
                    source_id,
                    resolved["id"],
                    "CALL",
                    resolution=resolved["resolution"],
                    confidence=resolved["confidence"],
                    line=getattr(call, "lineno", None),
                )

            if isinstance(call.func, ast.Attribute):
                model_name = self._extract_orm_model_name(call)
                if model_name and self._matches_orm_pattern(ast.unparse(call)):
                    self._add_named_relationship(
                        source_id, model_name, path, "PARTICLE", "PARTICLE_ENTANGLEMENT"
                    )

    def _resolve_call(
        self,
        call: ast.Call,
        path: Path,
        parent: Optional[str],
        local_types: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        func = call.func
        if isinstance(func, ast.Name):
            definition = self._resolve_name_reference(func.id, path)
            if definition:
                return {**definition, "resolution": "name", "confidence": 0.95}
            return None

        if not isinstance(func, ast.Attribute):
            return None

        receiver = func.value
        method_name = func.attr

        if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"} and parent:
            definition = self._definition_by_qualified_name(
                f"{self.identities.module_name(path)}.{parent}.{method_name}"
            )
            if definition:
                return {**definition, "resolution": "self_method", "confidence": 1.0}

        if isinstance(receiver, ast.Name) and receiver.id in local_types:
            class_definition = local_types[receiver.id]
            definition = self._definition_by_qualified_name(
                f"{class_definition['qualified_name']}.{method_name}"
            )
            if definition:
                return {**definition, "resolution": "local_instance", "confidence": 0.9}

        if isinstance(receiver, ast.Call):
            class_definition = self._resolve_class_reference(receiver.func, path)
            if class_definition:
                definition = self._definition_by_qualified_name(
                    f"{class_definition['qualified_name']}.{method_name}"
                )
                if definition:
                    return {**definition, "resolution": "constructed_instance", "confidence": 0.95}

        class_definition = self._resolve_class_reference(receiver, path)
        if class_definition:
            definition = self._definition_by_qualified_name(
                f"{class_definition['qualified_name']}.{method_name}"
            )
            if definition:
                return {**definition, "resolution": "class_method", "confidence": 0.95}

        qualified = self._qualified_expression(func, path)
        definition = self._definition_by_qualified_name(qualified) if qualified else None
        if definition:
            return {**definition, "resolution": "qualified_import", "confidence": 0.98}
        return None

    def _infer_local_types(
        self, owner_node: ast.AST, assignments: Iterable[ast.AST], path: Path
    ) -> Dict[str, Dict[str, str]]:
        local_types: Dict[str, Dict[str, str]] = {}
        if isinstance(owner_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_args = list(owner_node.args.posonlyargs) + list(owner_node.args.args) + list(owner_node.args.kwonlyargs)
            for argument in all_args:
                if argument.annotation:
                    definition = self._resolve_class_reference(argument.annotation, path)
                    if definition:
                        local_types[argument.arg] = definition

        for assignment in assignments:
            target_name: Optional[str] = None
            value: Optional[ast.AST] = None
            annotation: Optional[ast.AST] = None
            if isinstance(assignment, ast.Assign) and len(assignment.targets) == 1:
                if isinstance(assignment.targets[0], ast.Name):
                    target_name = assignment.targets[0].id
                    value = assignment.value
            elif isinstance(assignment, ast.AnnAssign) and isinstance(assignment.target, ast.Name):
                target_name = assignment.target.id
                value = assignment.value
                annotation = assignment.annotation

            definition = self._resolve_class_reference(annotation, path) if annotation else None
            if not definition and isinstance(value, ast.Call):
                definition = self._resolve_class_reference(value.func, path)
            if target_name and definition:
                local_types[target_name] = definition
        return local_types

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
