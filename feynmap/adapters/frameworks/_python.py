"""Shared helpers for Python framework adapters."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterable, List, Set

from feynmap.core import Evidence, EvidenceKind, NodeKind, SemanticGraph, SemanticNode

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__"}
DEPENDENCY_FILES = ("requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "setup.py", "setup.cfg")


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


def finalize(graph: SemanticGraph, framework: str) -> SemanticGraph:
    applied = graph.metadata.setdefault("frameworks_applied", [])
    if framework not in applied:
        applied.append(framework)
    graph.metadata["framework"] = framework
    graph.validate()
    return graph
