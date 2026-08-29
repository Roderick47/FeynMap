"""Top-level multi-language semantic analysis engine."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .adapters import AdapterRegistry, DjangoAdapter, FastAPIAdapter, FlaskAdapter, HTMLAdapter, JavaScriptAdapter, PythonAdapter
from .adapters.python_boundaries import enrich_python_boundaries
from .core import SemanticGraph
from .integration import IntegrationResolver
from .repository import merge_language_graphs

FRAMEWORK_AUTO_THRESHOLD = 0.35
LANGUAGE_AUTO_THRESHOLD = 0.01


class FeynMapEngine:
    """Analyze every applicable language, enrich frameworks, and resolve boundaries."""

    def __init__(self, registry: Optional[AdapterRegistry] = None, resolver: Optional[IntegrationResolver] = None) -> None:
        self.registry = registry or default_registry()
        self.resolver = resolver or IntegrationResolver()

    def analyze(self, project_path: str, language: str = "auto", framework: str = "auto") -> SemanticGraph:
        root = Path(project_path).resolve()
        if not root.exists():
            raise FileNotFoundError("project path does not exist: %s" % root)

        language_choices = self._select_languages(root, language)
        if not language_choices:
            raise ValueError("no registered language adapter recognized this repository")

        analyzed: List[Tuple[str, float, SemanticGraph]] = []
        explicit_frameworks = self._split_selection(framework)
        framework_off = (framework or "auto").lower() in {"none", "generic", "off"}

        for language_score, language_adapter in language_choices:
            graph = language_adapter.analyze(root)
            graph.metadata.setdefault("language_adapter", language_adapter.name)
            if language_adapter.name == "python":
                graph = enrich_python_boundaries(graph, root)

            if not framework_off:
                selected_frameworks: List[Tuple[float, object]] = []
                if (framework or "auto").lower() == "auto":
                    selected_frameworks = [
                        (score, adapter)
                        for score, adapter in self.registry.detect_frameworks(root, language_adapter.name)
                        if score >= FRAMEWORK_AUTO_THRESHOLD
                    ]
                else:
                    for name in explicit_frameworks:
                        adapter = self.registry.framework(name)
                        if adapter.language != language_adapter.name:
                            continue
                        selected_frameworks.append((adapter.detect_score(root), adapter))

                applied_scores = {}
                for score, framework_adapter in selected_frameworks:
                    graph = framework_adapter.enrich(graph, root)
                    applied_scores[framework_adapter.name] = round(float(score), 4)
                if applied_scores:
                    graph.metadata["framework_detection_scores"] = applied_scores
                    if len(applied_scores) == 1:
                        graph.metadata["framework_adapter"] = next(iter(applied_scores))
                        graph.metadata["framework_detection_score"] = next(iter(applied_scores.values()))

            analyzed.append((language_adapter.name, language_score, graph))

        merged = merge_language_graphs(root, analyzed)
        merged.metadata["language_selection"] = language
        merged.metadata["framework_selection"] = framework

        if len(analyzed) == 1:
            source_graph = analyzed[0][2]
            for key in ("adapter", "source_model", "language", "language_adapter", "framework_adapter", "framework_detection_score", "framework_detection_scores"):
                if key in source_graph.metadata:
                    merged.metadata[key] = source_graph.metadata[key]

        merged = self.resolver.resolve(merged)
        merged.validate()
        return merged

    def _select_languages(self, root: Path, selection: str) -> List[Tuple[float, object]]:
        normalized = (selection or "auto").lower()
        if normalized == "auto":
            return self.registry.detect_languages(root, minimum_score=LANGUAGE_AUTO_THRESHOLD)
        choices: List[Tuple[float, object]] = []
        for name in self._split_selection(selection):
            adapter = self.registry.language(name)
            score = adapter.detect_score(root)
            if score > 0:
                choices.append((score, adapter))
        return choices

    @staticmethod
    def _split_selection(value: str) -> List[str]:
        return [item.strip().lower() for item in str(value or "").split(",") if item.strip()]


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register_language(PythonAdapter())
    registry.register_language(HTMLAdapter())
    registry.register_language(JavaScriptAdapter())
    registry.register_framework(DjangoAdapter())
    registry.register_framework(FlaskAdapter())
    registry.register_framework(FastAPIAdapter())
    return registry
