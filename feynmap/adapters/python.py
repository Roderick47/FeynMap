"""Generic Python language adapter.

This module intentionally knows nothing about Django, Flask, FastAPI, or any
other Python framework. It extracts Python-defined facts (modules, symbols,
imports, calls, inheritance, and await relationships) into FeynMap's canonical
semantic graph. Framework adapters enrich that graph in a separate pass.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from feynmap.core import (
    EdgeKind,
    Evidence,
    EvidenceKind,
    NodeKind,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
    SourceLocation,
)

from .base import LanguageAdapter

EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
BUILTIN_NAMES = set(dir(builtins))


@dataclass
class Definition:
    id: str
    name: str
    qualified_name: str
    module: str
    path: Path
    node: ast.AST
    parent: Optional[str] = None


@dataclass
class ParsedModule:
    path: Path
    module: str
    tree: ast.Module
    imports: Dict[str, str] = field(default_factory=dict)
    definitions: Dict[str, Definition] = field(default_factory=dict)


class _ScopedBodyCollector(ast.NodeVisitor):
    """Collect calls/awaits without leaking into nested callable definitions."""

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


class PythonAdapter(LanguageAdapter):
    """Extract framework-neutral Python semantics using the standard-library AST."""

    name = "python"
    extensions = (".py",)

    def detect_score(self, project_path: Path) -> float:
        files = 0
        python_files = 0
        for path in self._iter_files(project_path):
            files += 1
            if path.suffix == ".py":
                python_files += 1
        if python_files == 0:
            return 0.0
        ratio = python_files / float(max(files, 1))
        manifest_bonus = 0.2 if any((project_path / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py", "Pipfile")) else 0.0
        return min(1.0, 0.55 + (ratio * 0.25) + manifest_bonus)

    def analyze(self, project_path: Path) -> SemanticGraph:
        root = project_path.resolve()
        modules, diagnostics = self._parse_modules(root)
        graph = SemanticGraph(metadata={"language": "python", "adapter": "python-ast", "frameworks_applied": []})

        module_ids: Dict[str, str] = {}
        definitions_by_qualified: Dict[str, Definition] = {}
        definitions_by_module_name: Dict[Tuple[str, str], Definition] = {}

        for parsed in modules:
            module_id = self._module_id(parsed.module)
            module_ids[parsed.module] = module_id
            graph.add_node(
                SemanticNode(
                    id=module_id,
                    name=parsed.module or parsed.path.stem,
                    qualified_name=parsed.module,
                    kind=NodeKind.MODULE,
                    language="python",
                    location=SourceLocation(self._relative(root, parsed.path), 1),
                    attributes={"python": {"path": self._relative(root, parsed.path)}},
                    evidence=[self._evidence(root, parsed.path, 1, "python.ast.module", "Python module parsed from source")],
                )
            )
            for definition in parsed.definitions.values():
                definitions_by_qualified[definition.qualified_name] = definition
                definitions_by_module_name[(parsed.module, definition.name)] = definition

        for parsed in modules:
            module_id = module_ids[parsed.module]
            for definition in parsed.definitions.values():
                graph.add_node(self._definition_node(root, definition))
                parent_id = module_id
                if definition.parent:
                    parent_qname = "%s.%s" % (parsed.module, definition.parent) if parsed.module else definition.parent
                    parent = definitions_by_qualified.get(parent_qname)
                    if parent:
                        parent_id = parent.id
                graph.add_edge(
                    self._edge(
                        parent_id,
                        definition.id,
                        EdgeKind.CONTAINS,
                        self._evidence(root, parsed.path, getattr(definition.node, "lineno", 1), "python.ast.contains", "Lexical containment"),
                    )
                )

        external_nodes: Set[str] = set()
        edge_keys: Set[Tuple[str, str, str]] = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}

        def ensure_external(qualified_name: str, location: SourceLocation) -> str:
            node_id = "python:external:%s" % qualified_name
            if node_id not in external_nodes and graph.node(node_id) is None:
                external_nodes.add(node_id)
                graph.add_node(
                    SemanticNode(
                        id=node_id,
                        name=qualified_name.rsplit(".", 1)[-1],
                        qualified_name=qualified_name,
                        kind=NodeKind.EXTERNAL_SYSTEM,
                        language="python",
                        attributes={"python": {"external": True}},
                        evidence=[Evidence(EvidenceKind.STATIC, "python.ast.import", "Imported Python dependency", location, 0.98)],
                    )
                )
            return node_id

        for parsed in modules:
            source_module_id = module_ids[parsed.module]
            for local_name, imported_qname in parsed.imports.items():
                target_id = self._resolve_import_target(imported_qname, module_ids, definitions_by_qualified)
                location = SourceLocation(self._relative(root, parsed.path), 1)
                if target_id is None:
                    target_id = ensure_external(imported_qname, location)
                self._add_edge_once(
                    graph,
                    edge_keys,
                    self._edge(source_module_id, target_id, EdgeKind.IMPORTS, Evidence(EvidenceKind.STATIC, "python.ast.import", "import %s" % imported_qname, location, 1.0), attributes={"local_name": local_name}),
                )

            for definition in parsed.definitions.values():
                if isinstance(definition.node, ast.ClassDef):
                    for base in definition.node.bases:
                        raw_base = _render_expr(base)
                        target_id = self._resolve_reference(raw_base, parsed, definition, module_ids, definitions_by_qualified, definitions_by_module_name)
                        if target_id is None and raw_base and raw_base not in BUILTIN_NAMES:
                            imported = self._expand_import_reference(raw_base, parsed.imports)
                            if imported:
                                target_id = ensure_external(imported, SourceLocation(self._relative(root, parsed.path), getattr(base, "lineno", getattr(definition.node, "lineno", 1))))
                        if target_id:
                            self._add_edge_once(
                                graph,
                                edge_keys,
                                self._edge(definition.id, target_id, EdgeKind.EXTENDS, self._evidence(root, parsed.path, getattr(base, "lineno", getattr(definition.node, "lineno", 1)), "python.ast.inheritance", "Python base class %s" % raw_base)),
                            )

                if not isinstance(definition.node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                collector = _ScopedBodyCollector(definition.node)
                collector.visit(definition.node)
                unresolved_calls: List[str] = []
                await_lines = {getattr(item.value, "lineno", None) for item in collector.awaits if isinstance(item.value, ast.Call)}
                for call in collector.calls:
                    raw_call = _render_expr(call.func)
                    target_id = self._resolve_call(call.func, parsed, definition, module_ids, definitions_by_qualified, definitions_by_module_name)
                    if target_id:
                        line = getattr(call, "lineno", getattr(definition.node, "lineno", 1))
                        self._add_edge_once(
                            graph,
                            edge_keys,
                            self._edge(definition.id, target_id, EdgeKind.CALLS, self._evidence(root, parsed.path, line, "python.ast.call", "Call to %s" % raw_call)),
                        )
                        if line in await_lines:
                            self._add_edge_once(
                                graph,
                                edge_keys,
                                self._edge(definition.id, target_id, EdgeKind.AWAITS, self._evidence(root, parsed.path, line, "python.ast.await", "Awaited call to %s" % raw_call)),
                            )
                    elif raw_call:
                        unresolved_calls.append(raw_call)
                if unresolved_calls:
                    semantic_node = graph.node(definition.id)
                    if semantic_node is not None:
                        semantic_node.attributes.setdefault("python", {})["unresolved_calls"] = sorted(set(unresolved_calls))

        graph.metadata.update({"module_count": len(modules), "parse_warnings": len(diagnostics), "source_model": "framework-neutral-python"})
        graph.validate()
        if diagnostics:
            graph.diagnostics["warnings"] = diagnostics + graph.diagnostics.get("warnings", [])
        return graph

    def _parse_modules(self, root: Path) -> Tuple[List[ParsedModule], List[str]]:
        modules: List[ParsedModule] = []
        warnings: List[str] = []
        for path in self._iter_files(root):
            if path.suffix != ".py":
                continue
            relative = self._relative(root, path)
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text, filename=relative)
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                warnings.append("could not parse %s: %s" % (relative, exc))
                continue
            module_name = self._module_name(root, path)
            parsed = ParsedModule(path=path, module=module_name, tree=tree)
            parsed.imports = self._collect_imports(tree, module_name)
            parsed.definitions = self._collect_definitions(path, module_name, tree)
            modules.append(parsed)
        return modules, warnings

    def _collect_definitions(self, path: Path, module: str, tree: ast.Module) -> Dict[str, Definition]:
        definitions: Dict[str, Definition] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_qname = _qualify(module, node.name)
                definitions[class_qname] = Definition(self._symbol_id(class_qname), node.name, class_qname, module, path, node)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_qname = "%s.%s" % (class_qname, child.name)
                        definitions[method_qname] = Definition(self._symbol_id(method_qname), child.name, method_qname, module, path, child, parent=node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = _qualify(module, node.name)
                definitions[qname] = Definition(self._symbol_id(qname), node.name, qname, module, path, node)
        return definitions

    def _collect_imports(self, tree: ast.Module, current_module: str) -> Dict[str, str]:
        imports: Dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    imports[local] = alias.name if alias.asname else alias.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                module = self._resolve_relative_module(current_module, node.module or "", node.level)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imports[alias.asname or alias.name] = _qualify(module, alias.name)
        return imports

    def _definition_node(self, root: Path, definition: Definition) -> SemanticNode:
        node = definition.node
        if isinstance(node, ast.ClassDef):
            kind = NodeKind.CLASS
            python_attrs = {"bases": [_render_expr(item) for item in node.bases], "decorators": [_render_expr(item) for item in node.decorator_list]}
        else:
            kind = NodeKind.METHOD if definition.parent else NodeKind.FUNCTION
            python_attrs = {
                "decorators": [_render_expr(item) for item in getattr(node, "decorator_list", [])],
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "parameters": _parameters(node),
                "returns": _render_expr(getattr(node, "returns", None)),
            }
        return SemanticNode(
            id=definition.id,
            name=definition.name,
            qualified_name=definition.qualified_name,
            kind=kind,
            language="python",
            framework=None,
            location=SourceLocation(self._relative(root, definition.path), getattr(node, "lineno", None), getattr(node, "end_lineno", None), getattr(node, "col_offset", None)),
            attributes={"python": python_attrs},
            evidence=[self._evidence(root, definition.path, getattr(node, "lineno", 1), "python.ast.definition", "Python %s definition" % kind.value)],
        )

    def _resolve_call(self, expr: ast.AST, parsed: ParsedModule, definition: Definition, module_ids: Dict[str, str], by_qualified: Dict[str, Definition], by_module_name: Dict[Tuple[str, str], Definition]) -> Optional[str]:
        return self._resolve_reference(_render_expr(expr), parsed, definition, module_ids, by_qualified, by_module_name)

    def _resolve_reference(self, raw: str, parsed: ParsedModule, definition: Definition, module_ids: Dict[str, str], by_qualified: Dict[str, Definition], by_module_name: Dict[Tuple[str, str], Definition]) -> Optional[str]:
        if not raw:
            return None
        if raw.startswith("self.") or raw.startswith("cls."):
            if definition.parent:
                qname = _qualify(parsed.module, "%s.%s" % (definition.parent, raw.split(".", 1)[1]))
                target = by_qualified.get(qname)
                return target.id if target else None
        if "." not in raw:
            same_module = by_module_name.get((parsed.module, raw))
            if same_module:
                return same_module.id
            imported = parsed.imports.get(raw)
            if imported:
                return self._resolve_import_target(imported, module_ids, by_qualified)
            if definition.parent:
                sibling = by_qualified.get(_qualify(parsed.module, "%s.%s" % (definition.parent, raw)))
                if sibling:
                    return sibling.id
            return None

        head, tail = raw.split(".", 1)
        imported_head = parsed.imports.get(head)
        if imported_head:
            expanded = "%s.%s" % (imported_head, tail)
            target = by_qualified.get(expanded)
            if target:
                return target.id
            module_target = module_ids.get(expanded)
            if module_target:
                return module_target
        class_target = by_module_name.get((parsed.module, head))
        if class_target:
            member = by_qualified.get("%s.%s" % (class_target.qualified_name, tail))
            if member:
                return member.id
        return None

    @staticmethod
    def _resolve_import_target(imported_qname: str, module_ids: Dict[str, str], definitions: Dict[str, Definition]) -> Optional[str]:
        definition = definitions.get(imported_qname)
        return definition.id if definition else module_ids.get(imported_qname)

    @staticmethod
    def _expand_import_reference(raw: str, imports: Dict[str, str]) -> Optional[str]:
        head, separator, tail = raw.partition(".")
        imported = imports.get(head)
        if not imported:
            return None
        return imported + (("." + tail) if separator else "")

    @staticmethod
    def _resolve_relative_module(current_module: str, module: str, level: int) -> str:
        if level <= 0:
            return module
        package = current_module.split(".")[:-1]
        keep = max(0, len(package) - (level - 1))
        prefix = package[:keep]
        return ".".join(prefix + ([module] if module else []))

    @staticmethod
    def _module_name(root: Path, path: Path) -> str:
        relative = path.relative_to(root).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) or root.name

    @staticmethod
    def _module_id(module: str) -> str:
        return "python:module:%s" % module

    @staticmethod
    def _symbol_id(qualified_name: str) -> str:
        return "python:symbol:%s" % qualified_name

    @staticmethod
    def _iter_files(root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                parts = path.relative_to(root).parts
            except ValueError:
                parts = path.parts
            if any(part in EXCLUDED_DIRS for part in parts):
                continue
            yield path

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    def _evidence(self, root: Path, path: Path, line: int, detector: str, detail: str) -> Evidence:
        return Evidence(EvidenceKind.STATIC, detector, detail, SourceLocation(self._relative(root, path), line), 1.0)

    @staticmethod
    def _edge(source: str, target: str, kind: EdgeKind, evidence: Evidence, attributes: Optional[Dict[str, object]] = None) -> SemanticEdge:
        raw = "%s|%s|%s|%s" % (source, target, kind.value, evidence.location.line if evidence.location else "")
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]
        return SemanticEdge("edge:%s" % digest, source, target, kind, evidence.confidence, [evidence], dict(attributes or {}))

    @staticmethod
    def _add_edge_once(graph: SemanticGraph, keys: Set[Tuple[str, str, str]], edge: SemanticEdge) -> None:
        key = (edge.source, edge.target, edge.kind.value)
        if key in keys:
            return
        keys.add(key)
        graph.add_edge(edge)


def _qualify(module: str, name: str) -> str:
    return "%s.%s" % (module, name) if module else name


def _render_expr(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    unparse = getattr(ast, "unparse", None)
    if unparse is not None:
        try:
            return unparse(node)
        except Exception:
            pass
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _render_expr(node.value)
        return "%s.%s" % (left, node.attr) if left else node.attr
    if isinstance(node, ast.Call):
        return _render_expr(node.func)
    if isinstance(node, ast.Subscript):
        return _render_expr(node.value)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return node.__class__.__name__


def _parameters(node: ast.AST) -> List[str]:
    args = getattr(node, "args", None)
    if args is None:
        return []
    items = list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs)
    names = [item.arg for item in items]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names
