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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set


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


class PythonSourceSession:
    """One immutable view of Python source for a single analysis invocation."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._paths: Optional[List[Path]] = None
        self._records: Dict[Path, PythonSourceFile] = {}
        self._imports_by_file: Optional[Dict[str, Set[str]]] = None
        self._repository_imports: Optional[Set[str]] = None

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
        key = Path(path).resolve()
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

    def imports_by_file(self) -> Dict[str, Set[str]]:
        if self._imports_by_file is None:
            result: Dict[str, Set[str]] = {}
            for record in self.records():
                if record.tree is None:
                    continue
                imports: Set[str] = set()
                for node in ast.walk(record.tree):
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
