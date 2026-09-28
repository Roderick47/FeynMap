"""Shared helpers for Python framework adapters."""
from __future__ import annotations

import ast
import heapq
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from feynmap.core import Evidence, EvidenceKind, NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import add_contract
from feynmap.adapters.python_source import get_python_source_session

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".feynmap"}
DEPENDENCY_FILES = ("requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "setup.py", "setup.cfg")
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def iter_python_files(root: Path) -> Iterable[Path]:
    yield from get_python_source_session(root).paths()


def dependency_text(root: Path) -> str:
    chunks: List[str] = []
    for name in DEPENDENCY_FILES:
        path = root / name
        if not path.exists() or not path.is_file():
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8").lower())
        except (OSError, UnicodeDecodeError):
            pass
    return "\n".join(chunks)


def imports_by_file(root: Path) -> Dict[str, Set[str]]:
    return get_python_source_session(root).imports_by_file()


def repository_imports(root: Path) -> Set[str]:
    return get_python_source_session(root).repository_imports()


def node_python(node: SemanticNode) -> Dict[str, object]:
    raw = node.attributes.get("python", {})
    return raw if isinstance(raw, dict) else {}


def node_bases(node: SemanticNode) -> List[str]:
    return [str(item) for item in node_python(node).get("bases", [])]


def node_decorators(node: SemanticNode) -> List[str]:
    return [str(item) for item in node_python(node).get("decorators", [])]


def node_imports(node: SemanticNode, imports: Dict[str, Set[str]]) -> Set[str]:
    if not node.location:
        return set()
    return imports.get(node.location.path, set())


def imported(imports: Set[str], prefix: str) -> bool:
    return any(value == prefix or value.startswith(prefix + ".") for value in imports)


def has_base(node: SemanticNode, *suffixes: str) -> bool:
    for base in node_bases(node):
        short = base.rsplit(".", 1)[-1]
        if any(base == suffix or base.endswith("." + suffix) or short == suffix for suffix in suffixes):
            return True
    return False


def has_decorator(node: SemanticNode, *suffixes: str) -> bool:
    for decorator in node_decorators(node):
        name = decorator.split("(", 1)[0]
        if any(name == suffix or name.endswith("." + suffix) for suffix in suffixes):
            return True
    return False


def route_method_decorator(node: SemanticNode) -> bool:
    return has_decorator(node, "get", "post", "put", "patch", "delete", "options", "head", "websocket", "api_route")


def mark_role(node: SemanticNode, framework: str, kind: NodeKind, role: str, detail: str, confidence: float = 0.98) -> None:
    node.kind = kind
    node.framework = framework
    framework_attrs = node.attributes.setdefault("framework", {})
    if isinstance(framework_attrs, dict):
        framework_attrs["name"] = framework
        framework_attrs["role"] = role
    node.evidence.append(Evidence(EvidenceKind.FRAMEWORK, "%s.adapter" % framework, detail, node.location, confidence))


class _CallableLineIndex:
    """Per-file callable intervals for framework AST-to-semantic ownership."""

    def __init__(self, graph: SemanticGraph) -> None:
        by_path: Dict[str, List[Tuple[int, int, int, int, SemanticNode]]] = {}
        for order, node in enumerate(graph.nodes):
            if (
                node.language != "python"
                or node.location is None
                or not node.location.path
                or node.kind not in {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.HANDLER}
            ):
                continue
            start = node.location.line or 1
            end = node.location.end_line or start
            span = end - start
            by_path.setdefault(node.location.path, []).append(
                (start, end, span, order, node)
            )
        self._by_path = {
            path: tuple(sorted(entries, key=lambda item: (item[0], item[3])))
            for path, entries in by_path.items()
        }

    def resolve_many(
        self,
        path: str,
        lines: Sequence[int],
    ) -> Dict[int, SemanticNode]:
        entries = self._by_path.get(path, ())
        if not entries or not lines:
            return {}

        result: Dict[int, SemanticNode] = {}
        active: List[Tuple[int, int, int, SemanticNode]] = []
        position = 0
        for line in sorted(set(int(value or 1) for value in lines)):
            while position < len(entries) and entries[position][0] <= line:
                start, end, span, order, node = entries[position]
                heapq.heappush(active, (span, order, end, node))
                position += 1
            while active and active[0][2] < line:
                heapq.heappop(active)
            if active:
                result[line] = active[0][3]
        return result

    def resolve(self, path: str, line: int) -> Optional[SemanticNode]:
        return self.resolve_many(path, [line]).get(int(line or 1))


def attach_decorator_http_contracts(graph: SemanticGraph, root: Path, framework: str) -> None:
    """Extract Flask/FastAPI-style HTTP/WebSocket routes directly from AST decorators."""
    source = get_python_source_session(root)
    callable_index = _CallableLineIndex(graph)
    for record in source.records():
        if record.tree is None:
            continue
        relative = record.relative
        tree = record.tree
        definitions = source.ast_index(record.path).functions
        owner_by_line = callable_index.resolve_many(
            relative,
            [getattr(definition, "lineno", 1) for definition in definitions],
        )
        for definition in definitions:
            semantic_node = owner_by_line.get(getattr(definition, "lineno", 1))
            if semantic_node is None or semantic_node.kind != NodeKind.HANDLER:
                continue
            for decorator in definition.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                decorator_name = _expr_name(decorator.func)
                short = decorator_name.rsplit(".", 1)[-1].lower()
                if short in set(HTTP_METHODS) | {"websocket"}:
                    route = _string(decorator.args[0]) if decorator.args else None
                    if not route:
                        continue
                    if short == "websocket":
                        add_contract(semantic_node, "websocket_server", route, 0.99, framework=framework)
                    else:
                        add_contract(semantic_node, "http_server", route, 0.99, methods=[short.upper()], framework=framework)
                elif short in {"route", "api_route"}:
                    route = _string(decorator.args[0]) if decorator.args else None
                    if not route:
                        continue
                    methods: List[str] = []
                    for keyword in decorator.keywords:
                        if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                            methods = [value for value in (_string(item) for item in keyword.value.elts) if value]
                    if not methods:
                        methods = ["GET"] if short == "route" else ["ANY"]
                    add_contract(semantic_node, "http_server", route, 0.99, methods=[item.upper() for item in methods], framework=framework)


def attach_django_url_contracts(graph: SemanticGraph, root: Path) -> None:
    """Map static Django path()/re_path() entries to uniquely named handlers."""
    by_name: Dict[str, List[SemanticNode]] = {}
    for node in graph.nodes:
        if node.language == "python" and node.kind == NodeKind.HANDLER:
            by_name.setdefault(node.name, []).append(node)

    source = get_python_source_session(root)
    for record in source.records():
        path = record.path
        if path.name != "urls.py" or record.tree is None:
            continue
        tree = record.tree
        for call in source.ast_index(record.path).calls:
            call_name = _expr_name(call.func)
            if call_name.rsplit(".", 1)[-1] not in {"path", "re_path"} or len(call.args) < 2:
                continue
            route = _string(call.args[0])
            handler_name = _handler_reference(call.args[1])
            candidates = by_name.get(handler_name, []) if handler_name else []
            if route is None or len(candidates) != 1:
                continue
            normalized = "/" + route.lstrip("/")
            add_contract(candidates[0], "http_server", normalized, 0.93, methods=["ANY"], framework="django", source_file=path.relative_to(root).as_posix())


def attach_template_render_contracts(graph: SemanticGraph, root: Path, framework: str) -> None:
    """Attach static template names to the smallest enclosing semantic callable."""
    source = get_python_source_session(root)
    callable_index = _CallableLineIndex(graph)
    for record in source.records():
        if record.tree is None:
            continue
        relative = record.relative
        tree = record.tree
        calls = source.ast_index(record.path).calls
        owner_by_line = callable_index.resolve_many(
            relative,
            [getattr(call, "lineno", 1) for call in calls],
        )
        for call in calls:
            call_name = _expr_name(call.func)
            template: Optional[str] = None
            if framework == "django" and call_name.rsplit(".", 1)[-1] in {"render", "render_to_string"}:
                index = 1 if call_name.rsplit(".", 1)[-1] == "render" else 0
                if len(call.args) > index:
                    template = _string(call.args[index])
            elif framework == "flask" and call_name.rsplit(".", 1)[-1] == "render_template":
                if call.args:
                    template = _string(call.args[0])
            elif framework == "fastapi" and call_name.rsplit(".", 1)[-1] == "TemplateResponse":
                if call.args:
                    template = _string(call.args[0])
                for keyword in call.keywords:
                    if keyword.arg == "name":
                        template = _string(keyword.value) or template
            if not template:
                continue
            semantic_node = owner_by_line.get(getattr(call, "lineno", 1))
            if semantic_node:
                add_contract(semantic_node, "template_render", template, 0.96, framework=framework, line=getattr(call, "lineno", 1))


def _node_for_line(graph: SemanticGraph, path: str, line: int) -> Optional[SemanticNode]:
    """Compatibility wrapper for callers that need a single line lookup."""
    return _CallableLineIndex(graph).resolve(path, line)


def _expr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _expr_name(node.value)
        return "%s.%s" % (left, node.attr) if left else node.attr
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    return ""


def _string(node: ast.AST) -> Optional[str]:
    # Python 3.8+ normalizes string syntax to Constant. Avoid deprecated
    # ast.Str/.s aliases so the parser remains compatible with newer Python.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _handler_reference(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "as_view":
        return _handler_reference(node.func.value)
    return ""


def finalize(graph: SemanticGraph, framework: str) -> SemanticGraph:
    applied = graph.metadata.setdefault("frameworks_applied", [])
    if framework not in applied:
        applied.append(framework)
    graph.metadata["framework"] = framework if len(applied) == 1 else None
    graph.validate()
    return graph
