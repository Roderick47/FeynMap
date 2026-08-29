"""Top-level semantic analysis engine."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .adapters import AdapterRegistry, DjangoAdapter, FastAPIAdapter, FlaskAdapter, PythonAdapter
from .core import SemanticGraph

FRAMEWORK_AUTO_THRESHOLD = 0.35


class FeynMapEngine:
    """Coordinate language extraction and independent framework enrichment."""

    def __init__(self, registry: Optional[AdapterRegistry] = None) -> None:
        self.registry = registry or default_registry()

    def analyze(self, project_path: str, language: str = "auto", framework: str = "auto") -> SemanticGraph:
        root = Path(project_path).resolve()
        if not root.exists():
            raise FileNotFoundError("project path does not exist: %s" % root)

        language_adapter = self.registry.detect_language(root) if language == "auto" else self.registry.language(language)
        graph = language_adapter.analyze(root)
        graph.metadata.setdefault("project_root", str(root))
        graph.metadata.setdefault("language_adapter", language_adapter.name)

        normalized_framework = (framework or "auto").lower()
        if normalized_framework not in {"none", "generic", "off"}:
            framework_adapter = None
            detection_score = None
            if normalized_framework == "auto":
                detected = self.registry.detect_framework(root, language_adapter.name)
                if detected is not None:
                    detection_score, candidate = detected
                    if detection_score >= FRAMEWORK_AUTO_THRESHOLD:
                        framework_adapter = candidate
            else:
                framework_adapter = self.registry.framework(normalized_framework)
                if framework_adapter.language != language_adapter.name:
                    raise ValueError(
                        "framework %r requires language %r, not %r"
                        % (framework_adapter.name, framework_adapter.language, language_adapter.name)
                    )
                detection_score = framework_adapter.detect_score(root)

            if framework_adapter is not None:
                graph = framework_adapter.enrich(graph, root)
                graph.metadata["framework_adapter"] = framework_adapter.name
                graph.metadata["framework_detection_score"] = round(float(detection_score or 0.0), 4)
            elif normalized_framework == "auto":
                graph.metadata["framework"] = None
                graph.metadata["framework_detection_score"] = round(float(detection_score or 0.0), 4)

        graph.validate()
        return graph


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register_language(PythonAdapter())
    registry.register_framework(DjangoAdapter())
    registry.register_framework(FlaskAdapter())
    registry.register_framework(FastAPIAdapter())
    return registry
