"""Lightweight framework-neutral JavaScript adapter.

This adapter deliberately uses deterministic source scanning and does not execute
project code. It is dependency-free so FeynMap's core remains portable. A future
Tree-sitter/TypeScript compiler adapter can replace or enrich these facts without
changing the semantic/integration contracts.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.integration import add_contract
from .base import LanguageAdapter

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "dist", "build", "coverage"}
JS_EXTENSIONS = {".js", ".mjs", ".cjs", ".jsx"}
IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
FUNCTION_RE = re.compile(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(%s)\s*\(" % IDENT)
ARROW_RE = re.compile(r"(?:export\s+)?(?:const|let|var)\s+(%s)\s*=\s*(?:async\s+)?(?:\([^)]*\)|%s)\s*=>" % (IDENT, IDENT))
CLASS_RE = re.compile(r"(?:export\s+)?(?:default\s+)?class\s+(%s)(?:\s+extends\s+(%s(?:\.%s)*))?" % (IDENT, IDENT, IDENT))
METHOD_RE = re.compile(r"(?:^|\n)\s*(?:async\s+)?(%s)\s*\([^)]*\)\s*\{" % IDENT)
IMPORT_RE = re.compile(r"(?:import\s+(?:[^;\n]*?\s+from\s+)?|require\s*\(\s*)['\"]([^'\"]+)['\"]")
CALL_RE = re.compile(r"(?<![\w$])(%s)\s*\(" % IDENT)
THIS_CALL_RE = re.compile(r"\bthis\.(%s)\s*\(" % IDENT)
CONTROL_CALLS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "new"}


@dataclass
class JSDefinition:
    id: str
    name: str
    kind: NodeKind
    path: Path
    start: int
    end: int
    line: int
    end_line: int
    parent: Optional[str] = None
    extends: Optional[str] = None


class JavaScriptAdapter(LanguageAdapter):
    name = "javascript"
    extensions = tuple(sorted(JS_EXTENSIONS))

    def detect_score(self, project_path: Path) -> float:
        count = sum(1 for path in self._iter_files(project_path) if path.suffix.lower() in JS_EXTENSIONS)
        if count == 0:
            return 0.0
        manifest_bonus = 0.15 if (project_path / "package.json").exists() else 0.0
        return min(1.0, 0.5 + min(count, 30) * 0.012 + manifest_bonus)

    def analyze(self, project_path: Path) -> SemanticGraph:
        root = project_path.resolve()
        graph = SemanticGraph(metadata={"language": "javascript", "adapter": "javascript-source", "frameworks_applied": []})
        parsed: List[Tuple[Path, str, List[JSDefinition]]] = []
        warnings: List[str] = []

        for path in self._iter_files(root):
            if path.suffix.lower() not in JS_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append("could not parse %s: %s" % (self._relative(root, path), exc))
                continue
            parsed.append((path, text, self._definitions(path, text)))

        module_nodes: Dict[str, SemanticNode] = {}
        definitions_by_name: Dict[str, List[JSDefinition]] = {}

        for path, text, definitions in parsed:
            relative = self._relative(root, path)
            module = SemanticNode(
                id="javascript:module:%s" % relative,
                name=path.name,
                qualified_name=relative,
                kind=NodeKind.MODULE,
                language="javascript",
                location=SourceLocation(relative, 1),
                attributes={"javascript": {"module": True}},
                evidence=[Evidence(EvidenceKind.STATIC, "javascript.source.module", "JavaScript module parsed from source", SourceLocation(relative, 1), 0.98)],
            )
            graph.add_node(module)
            module_nodes[relative] = module
            for definition in definitions:
                definitions_by_name.setdefault(definition.name, []).append(definition)

        edge_keys: Set[Tuple[str, str, str]] = set()
        for path, text, definitions in parsed:
            relative = self._relative(root, path)
            module = module_nodes[relative]
            local_by_name = {item.name: item for item in definitions}
            class_by_name = {item.name: item for item in definitions if item.kind == NodeKind.CLASS}

            for definition in definitions:
                node = SemanticNode(
                    id=definition.id,
                    name=definition.name,
                    qualified_name=self._qualified(relative, definition),
                    kind=definition.kind,
                    language="javascript",
                    location=SourceLocation(relative, definition.line, definition.end_line),
                    attributes={"javascript": {"parent": definition.parent, "extends": definition.extends}},
                    evidence=[Evidence(EvidenceKind.STATIC, "javascript.source.definition", "JavaScript %s definition" % definition.kind.value, SourceLocation(relative, definition.line), 0.96)],
                )
                graph.add_node(node)
                parent_id = module.id
                if definition.parent and definition.parent in class_by_name:
                    parent_id = class_by_name[definition.parent].id
                self._add_edge(graph, edge_keys, parent_id, node.id, EdgeKind.CONTAINS, relative, definition.line, "javascript.source.contains", 0.98)

            for definition in definitions:
                if definition.kind not in {NodeKind.FUNCTION, NodeKind.METHOD}:
                    continue
                body = text[definition.start:definition.end]
                for match in CALL_RE.finditer(body):
                    name = match.group(1)
                    if name in CONTROL_CALLS or name == definition.name:
                        continue
                    target = local_by_name.get(name)
                    if target and target.kind in {NodeKind.FUNCTION, NodeKind.METHOD}:
                        line = definition.line + body[:match.start()].count("\n")
                        self._add_edge(graph, edge_keys, definition.id, target.id, EdgeKind.CALLS, relative, line, "javascript.source.call", 0.91)
                if definition.parent:
                    sibling_methods = {item.name: item for item in definitions if item.parent == definition.parent and item.kind == NodeKind.METHOD}
                    for match in THIS_CALL_RE.finditer(body):
                        target = sibling_methods.get(match.group(1))
                        if target:
                            line = definition.line + body[:match.start()].count("\n")
                            self._add_edge(graph, edge_keys, definition.id, target.id, EdgeKind.CALLS, relative, line, "javascript.source.this_call", 0.94)

            for definition in definitions:
                if definition.kind == NodeKind.CLASS and definition.extends:
                    candidates = definitions_by_name.get(definition.extends.rsplit(".", 1)[-1], [])
                    local_target = next((item for item in candidates if item.path == path and item.kind == NodeKind.CLASS), None)
                    if local_target:
                        self._add_edge(graph, edge_keys, definition.id, local_target.id, EdgeKind.EXTENDS, relative, definition.line, "javascript.source.extends", 0.93)

            for imported in sorted(set(IMPORT_RE.findall(text))):
                target = self._resolve_module_import(root, path, imported, module_nodes)
                if target is None:
                    external_id = "javascript:external:%s" % imported
                    if graph.node(external_id) is None:
                        graph.add_node(
                            SemanticNode(
                                id=external_id,
                                name=imported.rsplit("/", 1)[-1],
                                qualified_name=imported,
                                kind=NodeKind.EXTERNAL_SYSTEM,
                                language="javascript",
                                attributes={"javascript": {"external": True}},
                                evidence=[Evidence(EvidenceKind.STATIC, "javascript.source.import", "Imported JavaScript dependency", SourceLocation(relative, 1), 0.96)],
                            )
                        )
                    target = graph.node(external_id)
                if target is not None:
                    self._add_edge(graph, edge_keys, module.id, target.id, EdgeKind.IMPORTS, relative, 1, "javascript.source.import", 0.96)
                if imported.endswith(".node"):
                    add_contract(module, "ffi_import", imported, 0.96, platform="node-native-addon")

            self._attach_integration_contracts(module, definitions, graph, relative, text)
            if re.search(r"require\.main\s*===\s*module|import\.meta\.main", text):
                add_contract(module, "cli_entrypoint", relative, 0.95, aliases=[path.name])

        graph.metadata.update({"module_count": len(parsed), "parse_warnings": len(warnings), "source_model": "framework-neutral-javascript"})
        graph.validate()
        if warnings:
            graph.diagnostics["warnings"] = warnings + graph.diagnostics.get("warnings", [])
        return graph

    def _definitions(self, path: Path, text: str) -> List[JSDefinition]:
        definitions: List[JSDefinition] = []
        class_spans: List[Tuple[str, int, int]] = []

        for match in CLASS_RE.finditer(text):
            body_start, end = self._brace_span(text, match.end())
            line = self._line(text, match.start())
            name = match.group(1)
            definitions.append(JSDefinition(self._id(path, name, line), name, NodeKind.CLASS, path, match.start(), end, line, self._line(text, end), extends=match.group(2)))
            class_spans.append((name, body_start, end))

        for match in FUNCTION_RE.finditer(text):
            name = match.group(1)
            _, end = self._brace_span(text, match.end())
            line = self._line(text, match.start())
            definitions.append(JSDefinition(self._id(path, name, line), name, NodeKind.FUNCTION, path, match.start(), end, line, self._line(text, end)))

        for match in ARROW_RE.finditer(text):
            name = match.group(1)
            brace = text.find("{", match.end(), min(len(text), match.end() + 240))
            if brace >= 0:
                _, end = self._brace_span(text, brace)
            else:
                newline = text.find("\n", match.end())
                end = len(text) if newline < 0 else newline
            line = self._line(text, match.start())
            definitions.append(JSDefinition(self._id(path, name, line), name, NodeKind.FUNCTION, path, match.start(), end, line, self._line(text, end)))

        for class_name, body_start, body_end in class_spans:
            class_body = text[body_start:body_end]
            for match in METHOD_RE.finditer(class_body):
                name = match.group(1)
                absolute = body_start + match.start()
                if name in {"if", "for", "while", "switch", "catch"}:
                    continue
                method_brace = body_start + match.end() - 1
                _, end = self._brace_span(text, method_brace)
                if end > body_end:
                    continue
                line = self._line(text, absolute)
                definitions.append(JSDefinition(self._id(path, "%s.%s" % (class_name, name), line), name, NodeKind.METHOD, path, absolute, end, line, self._line(text, end), parent=class_name))

        return sorted(definitions, key=lambda item: (item.start, item.kind.value, item.name))

    def _attach_integration_contracts(self, module: SemanticNode, definitions: List[JSDefinition], graph: SemanticGraph, relative: str, text: str) -> None:
        node_by_id = {node.id: node for node in graph.nodes}

        def owner(position: int) -> SemanticNode:
            containing = [item for item in definitions if item.kind in {NodeKind.FUNCTION, NodeKind.METHOD} and item.start <= position <= item.end]
            if containing:
                containing.sort(key=lambda item: item.end - item.start)
                return node_by_id[containing[0].id]
            return module

        for match in re.finditer(r"\bfetch\s*\(\s*['\"]([^'\"]+)['\"]", text):
            tail = text[match.end(): min(len(text), match.end() + 220)]
            method_match = re.search(r"\bmethod\s*:\s*['\"]([A-Za-z]+)['\"]", tail)
            add_contract(owner(match.start()), "http_client", match.group(1), 0.96, method=(method_match.group(1).upper() if method_match else "GET"), line=self._line(text, match.start()))

        for match in re.finditer(r"\baxios\.(get|post|put|patch|delete|head|options)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
            add_contract(owner(match.start()), "http_client", match.group(2), 0.97, method=match.group(1).upper(), line=self._line(text, match.start()))

        for match in re.finditer(r"(?:new\s+)?WebSocket\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "websocket_client", match.group(1), 0.96, line=self._line(text, match.start()))

        for match in re.finditer(r"\b(?:child_process\.)?(spawn|exec|execFile|fork)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "process_spawn", match.group(2), 0.92, api=match.group(1), line=self._line(text, match.start()))

        for match in re.finditer(r"\b(?:fs\.)?(readFile|readFileSync|createReadStream)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "file_read", match.group(2), 0.94, api=match.group(1), line=self._line(text, match.start()))
        for match in re.finditer(r"\b(?:fs\.)?(writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "file_write", match.group(2), 0.94, api=match.group(1), line=self._line(text, match.start()))

        for match in re.finditer(r"\bipcRenderer\.(?:send|invoke)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "ipc_send", match.group(1), 0.97, platform="electron", line=self._line(text, match.start()))
        for match in re.finditer(r"\bipcMain\.(?:on|handle|once)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "ipc_receive", match.group(1), 0.97, platform="electron", line=self._line(text, match.start()))

        for match in re.finditer(r"\b(?:Linking\.openURL|openURL)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            add_contract(owner(match.start()), "deep_link", match.group(1), 0.9, platform="app", line=self._line(text, match.start()))

        for match in re.finditer(r"\bNativeModules\.([A-Za-z_$][A-Za-z0-9_$]*)\.", text):
            add_contract(owner(match.start()), "ffi_import", match.group(1), 0.88, platform="react-native", line=self._line(text, match.start()))
        for match in re.finditer(r"\bwindow\.ReactNativeWebView\.postMessage\s*\(", text):
            add_contract(owner(match.start()), "ipc_send", "react-native-webview", 0.9, platform="react-native-webview", line=self._line(text, match.start()))
        for match in re.finditer(r"\bwebkit\.messageHandlers\.([A-Za-z_$][A-Za-z0-9_$]*)\.postMessage\s*\(", text):
            add_contract(owner(match.start()), "ipc_send", match.group(1), 0.92, platform="ios-wkwebview", line=self._line(text, match.start()))

        for match in re.finditer(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)", text):
            add_contract(owner(match.start()), "config_read", "env:%s" % match.group(1), 0.98, line=self._line(text, match.start()))

    def _resolve_module_import(self, root: Path, source: Path, imported: str, modules: Dict[str, SemanticNode]) -> Optional[SemanticNode]:
        if not imported.startswith("."):
            return None
        base = source.parent / imported
        candidates = [base]
        if base.suffix.lower() not in JS_EXTENSIONS:
            candidates.extend(Path(str(base) + ext) for ext in JS_EXTENSIONS)
            candidates.extend(base / ("index" + ext) for ext in JS_EXTENSIONS)
        for candidate in candidates:
            try:
                relative = candidate.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if relative in modules:
                return modules[relative]
        return None

    @staticmethod
    def _brace_span(text: str, start: int) -> Tuple[int, int]:
        brace = text.find("{", start)
        if brace < 0:
            newline = text.find("\n", start)
            end = len(text) if newline < 0 else newline
            return start, end
        depth = 0
        quote: Optional[str] = None
        escape = False
        i = brace
        while i < len(text):
            char = text[i]
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    quote = None
            else:
                if char in {"'", '"', "`"}:
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return brace, i + 1
            i += 1
        return brace, len(text)

    @staticmethod
    def _line(text: str, position: int) -> int:
        return text.count("\n", 0, max(0, position)) + 1

    @staticmethod
    def _id(path: Path, name: str, line: int) -> str:
        raw = "%s|%s|%s" % (path.as_posix(), name, line)
        return "javascript:symbol:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _qualified(relative: str, definition: JSDefinition) -> str:
        base = relative.replace("/", ".")
        return "%s.%s%s" % (base, (definition.parent + ".") if definition.parent else "", definition.name)

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

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

    @staticmethod
    def _add_edge(graph: SemanticGraph, keys: Set[Tuple[str, str, str]], source: str, target: str, kind: EdgeKind, path: str, line: int, detector: str, confidence: float) -> None:
        key = (source, target, kind.value)
        if key in keys:
            return
        keys.add(key)
        raw = "%s|%s|%s|%s" % (source, target, kind.value, line)
        evidence = Evidence(EvidenceKind.STATIC, detector, "JavaScript %s relationship" % kind.value, SourceLocation(path, line), confidence)
        graph.add_edge(SemanticEdge("edge:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14], source, target, kind, confidence, [evidence]))
