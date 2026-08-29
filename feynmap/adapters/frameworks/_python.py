"""Shared helpers for Python framework adapters."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from feynmap.core import Evidence, EvidenceKind, NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import add_contract

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__"}
DEPENDENCY_FILES = ("requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "setup.py", "setup.cfg")
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in EXCLUDED for part in parts):
            continue
        yield path


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
    result: Dict[str, Set[str]] = {}
    for path in iter_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        imports: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        result[path.relative_to(root).as_posix()] = imports
    return result


def repository_imports(root: Path) -> Set[str]:
    combined: Set[str] = set()
    for imports in imports_by_file(root).values():
        combined.update(imports)
    return combined


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


def attach_decorator_http_contracts(graph: SemanticGraph, framework: str) -> None:
    """Extract Flask/FastAPI-style HTTP/WebSocket routes from decorators."""
    for node in graph.nodes:
        if node.language != "python" or node.kind != NodeKind.HANDLER:
            continue
        for decorator in node_decorators(node):
            match = re.search(r"\.?(get|post|put|patch|delete|options|head|websocket)\s*\(\s*['\"]([^'\"]+)['\"]", decorator, re.IGNORECASE)
            if match:
                method = match.group(1).upper()
                path = match.group(2)
                if method == "WEBSOCKET":
                    add_contract(node, "websocket_server", path, 0.98, framework=framework)
                else:
                    add_contract(node, "http_server", path, 0.99, methods=[method], framework=framework)
                continue
            route_match = re.search(r"\.route\s*\(\s*['\"]([^'\"]+)['\"](.*)\)", decorator, re.IGNORECASE)
            if route_match:
                tail = route_match.group(2)
                methods_match = re.search(r"methods\s*=\s*\[([^\]]+)\]", tail, re.IGNORECASE)
                methods = [item.upper() for item in re.findall(r"['\"]([A-Za-z]+)['\"]", methods_match.group(1))] if methods_match else ["GET"]
                add_contract(node, "http_server", route_match.group(1), 0.99, methods=methods or ["GET"], framework=framework)


def attach_django_url_contracts(graph: SemanticGraph, root: Path) -> None:
    """Map static Django path()/re_path() entries to uniquely named handlers."""
    by_name: Dict[str, List[SemanticNode]] = {}
    for node in graph.nodes:
        if node.language == "python" and node.kind == NodeKind.HANDLER:
            by_name.setdefault(node.name, []).append(node)

    for path in iter_python_files(root):
        if path.name != "urls.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
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
    for path in iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
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
            semantic_node = _node_for_line(graph, relative, getattr(call, "lineno", 1))
            if semantic_node:
                add_contract(semantic_node, "template_render", template, 0.96, framework=framework, line=getattr(call, "lineno", 1))


def _node_for_line(graph: SemanticGraph, path: str, line: int) -> Optional[SemanticNode]:
    candidates: List[SemanticNode] = []
    for node in graph.nodes:
        if node.language != "python" or not node.location or node.location.path != path:
            continue
        if node.kind not in {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.HANDLER}:
            continue
        start = node.location.line or 1
        end = node.location.end_line or start
        if start <= line <= end:
            candidates.append(node)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.location.end_line or item.location.line or 1) - (item.location.line or 1))
    return candidates[0]


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
    if isinstance(node, ast.Str):
        return node.s
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
