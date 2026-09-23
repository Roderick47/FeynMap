"""Analysis-scoped Python source cache shared by semantic passes.

The normal FeynMap engine opens one session for a repository analysis so
language extraction, enrichment, and framework detection can reuse the same
source text and AST objects. Callers that use an adapter/enricher directly still
work: they receive an isolated fallback session for that call.

The cache is intentionally analysis-scoped. It is not a process-global source
cache and therefore cannot silently retain stale ASTs after repository changes.
"""
from __future__ import annotations

import ast
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple


EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", ".feynmap",
}


@dataclass(frozen=True)
class PythonSourceFile:
    path: Path
    relative: str
    text: Optional[str]
    tree: Optional[ast.Module]
    error: Optional[str] = None


@dataclass(frozen=True)
class PythonAstIndex:
    """Reusable structural slices from one full AST traversal."""

    imports: Tuple[ast.AST, ...]
    calls: Tuple[ast.Call, ...]
    functions: Tuple[ast.AST, ...]
    classes: Tuple[ast.ClassDef, ...]


class _ScopedCallableCollector(ast.NodeVisitor):
    """Match FeynMap's historical callable traversal exactly, once per AST node."""

    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.calls: List[ast.Call] = []
        self.awaits: List[ast.Await] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self.awaits.append(node)
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


class PythonSourceSession:
    """One immutable view of Python source for a single analysis invocation."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._paths: Optional[List[Path]] = None
        self._records: Dict[Path, PythonSourceFile] = {}
        self._imports_by_file: Optional[Dict[str, Set[str]]] = None
        self._repository_imports: Optional[Set[str]] = None
        self._ast_indexes: Dict[Path, PythonAstIndex] = {}
        self._scoped_callables: Dict[int, Tuple[Tuple[ast.Call, ...], Tuple[ast.Await, ...]]] = {}

    def paths(self) -> List[Path]:
        if self._paths is None:
            paths: List[Path] = []
            for path in self.root.rglob("*.py"):
                if not path.is_file():
                    continue
                try:
                    parts = path.relative_to(self.root).parts
                except ValueError:
                    parts = path.parts
                if any(part in EXCLUDED_DIRS for part in parts):
                    continue
                paths.append(path)
            self._paths = sorted(paths, key=lambda item: self.relative(item))
        return list(self._paths)

    def relative(self, path: Path) -> str:
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).as_posix()

    def record(self, path: Path) -> PythonSourceFile:
        path_value = Path(path)
        key = path_value if path_value.is_absolute() else path_value.resolve()
        cached = self._records.get(key)
        if cached is not None:
            return cached

        relative = self.relative(key)
        try:
            text = key.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=relative)
            record = PythonSourceFile(key, relative, text, tree, None)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            record = PythonSourceFile(key, relative, None, None, str(exc))
        self._records[key] = record
        return record

    def records(self) -> Iterable[PythonSourceFile]:
        for path in self.paths():
            yield self.record(path)

    def ast_index(self, path: Path) -> PythonAstIndex:
        path_value = Path(path)
        key = path_value if path_value.is_absolute() else path_value.resolve()
        cached = self._ast_indexes.get(key)
        if cached is not None:
            return cached

        record = self.record(key)
        imports: List[ast.AST] = []
        calls: List[ast.Call] = []
        functions: List[ast.AST] = []
        classes: List[ast.ClassDef] = []
        scoped_calls: Dict[int, List[Tuple[Tuple[int, ...], ast.Call]]] = {}
        scoped_awaits: Dict[int, List[Tuple[Tuple[int, ...], ast.Await]]] = {}

        if record.tree is not None:
            # Match ast.walk's breadth-first ordering while carrying callable
            # ownership. A nested function/lambda/class is a scope boundary,
            # matching the historical scoped collectors exactly.
            queue = deque([(record.tree, None, ())])
            while queue:
                node, owner, path_key = queue.popleft()

                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.append(node)
                if isinstance(node, ast.Call):
                    calls.append(node)
                    if owner is not None:
                        scoped_calls.setdefault(id(owner), []).append((path_key, node))
                if isinstance(node, ast.Await) and owner is not None:
                    scoped_awaits.setdefault(id(owner), []).append((path_key, node))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node)
                if isinstance(node, ast.ClassDef):
                    classes.append(node)

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body_ids = {id(child) for child in node.body}
                    for child_index, child in enumerate(ast.iter_child_nodes(node)):
                        child_owner = node if id(child) in body_ids else None
                        queue.append((child, child_owner, path_key + (child_index,)))
                    continue

                if isinstance(node, ast.Lambda):
                    for child_index, child in enumerate(ast.iter_child_nodes(node)):
                        queue.append((child, node if child is node.body else None, path_key + (child_index,)))
                    continue

                if isinstance(node, ast.ClassDef):
                    for child_index, child in enumerate(ast.iter_child_nodes(node)):
                        queue.append((child, None, path_key + (child_index,)))
                    continue

                for child_index, child in enumerate(ast.iter_child_nodes(node)):
                    queue.append((child, owner, path_key + (child_index,)))

        for owner_id, owner_calls in scoped_calls.items():
            existing = self._scoped_callables.get(owner_id)
            calls_in_historical_order = tuple(
                node for _, node in sorted(owner_calls, key=lambda item: item[0])
            )
            awaits_in_historical_order = tuple(
                node
                for _, node in sorted(
                    scoped_awaits.get(owner_id, ()),
                    key=lambda item: item[0],
                )
            )
            if existing is None:
                self._scoped_callables[owner_id] = (
                    calls_in_historical_order,
                    awaits_in_historical_order,
                )
        for owner_id, owner_awaits in scoped_awaits.items():
            if owner_id not in self._scoped_callables:
                awaits_in_historical_order = tuple(
                    node for _, node in sorted(owner_awaits, key=lambda item: item[0])
                )
                self._scoped_callables[owner_id] = ((), awaits_in_historical_order)

        # Ensure callable nodes with no calls/awaits still become cache hits.
        for node in functions:
            self._scoped_callables.setdefault(id(node), ((), ()))

        index = PythonAstIndex(
            imports=tuple(imports),
            calls=tuple(calls),
            functions=tuple(functions),
            classes=tuple(classes),
        )
        self._ast_indexes[key] = index
        return index

    def scoped_callable(self, node: ast.AST) -> Tuple[Tuple[ast.Call, ...], Tuple[ast.Await, ...]]:
        key = id(node)
        cached = self._scoped_callables.get(key)
        if cached is not None:
            return cached
        collector = _ScopedCallableCollector(node)
        collector.visit(node)
        result = (tuple(collector.calls), tuple(collector.awaits))
        self._scoped_callables[key] = result
        return result

    def scoped_calls(self, node: ast.AST) -> Tuple[ast.Call, ...]:
        return self.scoped_callable(node)[0]

    def scoped_awaits(self, node: ast.AST) -> Tuple[ast.Await, ...]:
        return self.scoped_callable(node)[1]

    def imports_by_file(self) -> Dict[str, Set[str]]:
        if self._imports_by_file is None:
            result: Dict[str, Set[str]] = {}
            for record in self.records():
                if record.tree is None:
                    continue
                imports: Set[str] = set()
                for node in self.ast_index(record.path).imports:
                    if isinstance(node, ast.Import):
                        imports.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module)
                result[record.relative] = imports
            self._imports_by_file = result
        return {path: set(values) for path, values in self._imports_by_file.items()}

    def repository_imports(self) -> Set[str]:
        if self._repository_imports is None:
            combined: Set[str] = set()
            for imports in self.imports_by_file().values():
                combined.update(imports)
            self._repository_imports = combined
        return set(self._repository_imports)


_ACTIVE_SESSION: ContextVar[Optional[PythonSourceSession]] = ContextVar(
    "feynmap_python_source_session", default=None
)


def get_python_source_session(root: Path) -> PythonSourceSession:
    resolved = Path(root).resolve()
    current = _ACTIVE_SESSION.get()
    if current is not None and current.root == resolved:
        return current
    return PythonSourceSession(resolved)


@contextmanager
def python_source_session(root: Path) -> Iterator[PythonSourceSession]:
    """Activate one source cache for all Python work in this analysis scope."""
    session = PythonSourceSession(Path(root))
    token = _ACTIVE_SESSION.set(session)
    try:
        yield session
    finally:
        _ACTIVE_SESSION.reset(token)
