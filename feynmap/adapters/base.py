"""Adapter contracts for bringing languages and frameworks into FeynMap."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from feynmap.core import SemanticGraph


class LanguageAdapter(ABC):
    """Extract language-level facts only.

    Language adapters must not classify framework roles. They parse syntax,
    symbols, imports, calls, inheritance, and other semantics defined by the
    source language itself.
    """

    name = "unknown"
    extensions: Iterable[str] = ()

    @abstractmethod
    def detect_score(self, project_path: Path) -> float:
        """Return a 0..1 likelihood that this adapter should analyze the repository."""

    @abstractmethod
    def analyze(self, project_path: Path) -> SemanticGraph:
        """Produce language facts without framework-specific interpretation."""


class FrameworkAdapter(ABC):
    """Enrich an existing language graph with framework semantics."""

    name = "unknown"
    language = "unknown"

    @abstractmethod
    def detect_score(self, project_path: Path) -> float:
        """Return a 0..1 framework detection score."""

    @abstractmethod
    def enrich(self, graph: SemanticGraph, project_path: Path) -> SemanticGraph:
        """Add framework roles/evidence without replacing language-level facts."""


class AdapterRegistry:
    def __init__(self) -> None:
        self._languages: Dict[str, LanguageAdapter] = {}
        self._frameworks: Dict[str, FrameworkAdapter] = {}

    def register_language(self, adapter: LanguageAdapter) -> None:
        self._languages[adapter.name] = adapter

    def register_framework(self, adapter: FrameworkAdapter) -> None:
        self._frameworks[adapter.name] = adapter

    @property
    def languages(self) -> List[str]:
        return sorted(self._languages)

    @property
    def frameworks(self) -> List[str]:
        return sorted(self._frameworks)

    def language(self, name: str) -> LanguageAdapter:
        try:
            return self._languages[name]
        except KeyError:
            raise ValueError("unsupported language %r; available: %s" % (name, ", ".join(self.languages)))

    def framework(self, name: str) -> FrameworkAdapter:
        try:
            return self._frameworks[name]
        except KeyError:
            raise ValueError("unsupported framework %r; available: %s" % (name, ", ".join(self.frameworks)))

    def frameworks_for_language(self, language: str) -> List[FrameworkAdapter]:
        return sorted(
            (adapter for adapter in self._frameworks.values() if adapter.language == language),
            key=lambda adapter: adapter.name,
        )

    def detect_language(self, project_path: Path) -> LanguageAdapter:
        if not self._languages:
            raise RuntimeError("no language adapters are registered")
        ranked = sorted(
            ((adapter.detect_score(project_path), adapter) for adapter in self._languages.values()),
            key=lambda item: item[0],
            reverse=True,
        )
        score, adapter = ranked[0]
        if score <= 0:
            raise ValueError("no registered language adapter recognized this repository")
        return adapter

    def detect_framework(self, project_path: Path, language: str) -> Optional[Tuple[float, FrameworkAdapter]]:
        candidates = self.frameworks_for_language(language)
        if not candidates:
            return None
        ranked = sorted(
            ((adapter.detect_score(project_path), adapter) for adapter in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        score, adapter = ranked[0]
        return (score, adapter) if score > 0 else None
