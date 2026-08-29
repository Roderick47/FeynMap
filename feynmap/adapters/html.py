"""Framework-neutral HTML/template adapter.

The adapter extracts UI surfaces and integration boundaries without assuming a
specific backend framework. Template syntax is preserved as text; framework
adapters/resolvers decide what it means later.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from feynmap.core import Evidence, EvidenceKind, NodeKind, SemanticGraph, SemanticNode, SourceLocation
from feynmap.integration import add_contract
from .base import LanguageAdapter

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "dist", "build"}
HTML_EXTENSIONS = {".html", ".htm"}
EVENT_ATTR_RE = re.compile(r"^on[a-z]+$", re.IGNORECASE)
HANDLER_RE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*(?:\(|$)")
DJANGO_STATIC_RE = re.compile(r"\{\%\s*static\s+['\"]([^'\"]+)['\"]\s*\%\}")


class _HTMLCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: List[Tuple[str, int]] = []
        self.events: List[Tuple[str, str, int]] = []
        self.http: List[Tuple[str, str, int, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values: Dict[str, str] = {str(key).lower(): str(value or "") for key, value in attrs}
        line = self.getpos()[0]
        tag_lower = tag.lower()

        if tag_lower == "script" and values.get("src"):
            self.scripts.append((values["src"], line))

        for key, value in values.items():
            if EVENT_ATTR_RE.match(key) and value:
                match = HANDLER_RE.match(value)
                if match:
                    self.events.append((key, match.group(1), line))

        if tag_lower == "form" and values.get("action"):
            self.http.append((values.get("method", "GET").upper(), values["action"], line, "form"))

        for method in ("get", "post", "put", "patch", "delete"):
            attr = "hx-%s" % method
            if values.get(attr):
                self.http.append((method.upper(), values[attr], line, "htmx"))

        if tag_lower == "a" and values.get("href", "").startswith("/"):
            self.http.append(("GET", values["href"], line, "navigation"))


class HTMLAdapter(LanguageAdapter):
    name = "html"
    extensions = tuple(sorted(HTML_EXTENSIONS))

    def detect_score(self, project_path: Path) -> float:
        count = sum(1 for path in self._iter_files(project_path) if path.suffix.lower() in HTML_EXTENSIONS)
        if count == 0:
            return 0.0
        return min(1.0, 0.55 + min(count, 25) * 0.015)

    def analyze(self, project_path: Path) -> SemanticGraph:
        root = project_path.resolve()
        graph = SemanticGraph(metadata={"language": "html", "adapter": "html-stdlib", "frameworks_applied": []})
        warnings: List[str] = []
        for path in self._iter_files(root):
            if path.suffix.lower() not in HTML_EXTENSIONS:
                continue
            relative = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append("could not parse %s: %s" % (relative, exc))
                continue

            collector = _HTMLCollector()
            try:
                collector.feed(text)
            except Exception as exc:
                warnings.append("HTML parser warning in %s: %s" % (relative, exc))

            node = SemanticNode(
                id="html:file:%s" % relative,
                name=path.name,
                qualified_name=relative,
                kind=NodeKind.UI_SURFACE,
                language="html",
                location=SourceLocation(relative, 1),
                attributes={"html": {"template": self._looks_like_template(text)}},
                evidence=[Evidence(EvidenceKind.STATIC, "html.parser", "HTML document parsed from source", SourceLocation(relative, 1), 1.0)],
            )

            for src, line in collector.scripts:
                target = self._normalize_template_asset(src)
                add_contract(node, "script_load", target, 0.98, line=line)
            for event, handler, line in collector.events:
                add_contract(node, "event_handler", handler, 0.94, event=event, line=line)
            for method, target, line, source in collector.http:
                add_contract(node, "http_client", target, 0.92 if source != "navigation" else 0.78, method=method, source=source, line=line)

            graph.add_node(node)

        graph.metadata.update({"document_count": len(graph.nodes), "parse_warnings": len(warnings), "source_model": "framework-neutral-html"})
        graph.validate()
        if warnings:
            graph.diagnostics["warnings"] = warnings + graph.diagnostics.get("warnings", [])
        return graph

    @staticmethod
    def _normalize_template_asset(value: str) -> str:
        match = DJANGO_STATIC_RE.search(value)
        return match.group(1) if match else value

    @staticmethod
    def _looks_like_template(text: str) -> bool:
        return any(marker in text for marker in ("{{", "{%", "<%", "${"))

    @staticmethod
    def _iter_files(root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                parts = path.relative_to(root).parts
            except ValueError:
                parts = path.parts
            if any(part in EXCLUDED for part in parts):
                continue
            yield path
