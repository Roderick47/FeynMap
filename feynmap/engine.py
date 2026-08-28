"""Top-level semantic analysis engine."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .adapters import AdapterRegistry, PythonAdapter
from .core import SemanticGraph


class FeynMapEngine:
    """Coordinate language adapters and produce one canonical semantic graph."""

    def __init__(self, registry: Optional[AdapterRegistry] = None) -> None:
        self.registry = registry or default_registry()

    def analyze(self, project_path: str, language: str = "auto", framework: str = "auto") -> SemanticGraph:
        root = Path(project_path).resolve()
        if not root.exists():
            raise FileNotFoundError("project path does not exist: %s" % root)
        adapter = self.registry.detect_language(root) if language == "auto" else self.registry.language(language)
        graph = adapter.analyze(root, framework=framework)
        graph.metadata.setdefault("project_root", str(root))
        graph.metadata.setdefault("language_adapter", adapter.name)
        graph.validate()
        return graph


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register_language(PythonAdapter())
    return registry
