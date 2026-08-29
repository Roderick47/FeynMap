"""Resolve Python package re-exports using explicit static alias evidence.

This pass handles public import surfaces such as::

    # package/__init__.py
    from .implementation import PublicClass
    __all__ = ["PublicClass"]

and transitive chains such as ``package.PublicClass -> package.sub.PublicClass
-> package.sub.implementation.PublicClass``.

A re-export is resolved only when the alias chain terminates at exactly one
known semantic definition. Cycles, star imports, dynamic ``__all__`` values,
and ambiguous bindings remain unresolved.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation


EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
ResolvedAlias = Tuple[str, List[str], float]


@dataclass(frozen=True)
class ImportBinding:
    local_name: str
    qualified_name: str
    line: int


@dataclass
class ParsedPythonFile:
    path: Path
    module: str
    is_package: bool
    tree: ast.Module
    imports: Dict[str, ImportBinding]


class _ScopedCallCollector(ast.NodeVisitor):
    """Collect calls from one callable without descending into nested callables."""

    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.calls: List[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
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


def python_reexport_aliases(graph: SemanticGraph, project_path: Path) -> Dict[str, ResolvedAlias]:
    """Return uniquely resolved package aliases for reuse by other Python passes.

    The mapping key is the public/re-exported qualified name. The value is the
    canonical target qualified name, the full alias chain, and confidence. This
    function is intentionally read-only: it does not mutate the graph.
    """
    root = project_path.resolve()
    nodes_by_qname: Dict[str, SemanticNode] = {
        node.qualified_name: node
        for node in graph.nodes
        if node.language == "python" and node.qualified_name
    }
    if not nodes_by_qname:
        return {}
    parsed = _parse_python_files(root)
    resolved, _ = _resolved_alias_index(parsed, nodes_by_qname)
    return resolved


def enrich_python_reexports(graph: SemanticGraph, project_path: Path) -> SemanticGraph:
    """Resolve statically provable package re-export aliases and calls through them."""
    root = project_path.resolve()
    nodes_by_qname: Dict[str, SemanticNode] = {
        node.qualified_name: node
        for node in graph.nodes
        if node.language == "python" and node.qualified_name
    }
    if not nodes_by_qname:
        return graph

    parsed = _parse_python_files(root)
    resolved_aliases, ambiguous_aliases = _resolved_alias_index(parsed, nodes_by_qname)
    raw_aliases, _ = _package_aliases(parsed)

    call_edges_added = 0
    import_edges_added = 0
    repaired_external_import_edges = 0
    existing_keys = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
    edges_to_remove: Set[str] = set()

    for parsed_file in parsed:
        module_node = nodes_by_qname.get(parsed_file.module)
        if module_node is None:
            module_node = graph.node("python:module:%s" % parsed_file.module)

        for binding in parsed_file.imports.values():
            resolved = _binding_resolution(binding.qualified_name, resolved_aliases, nodes_by_qname)
            if resolved is None:
                continue
            target_qname, chain, confidence, strategy = resolved
            target_node = nodes_by_qname.get(target_qname)
            if target_node is None:
                continue

            if module_node is not None:
                key = (module_node.id, target_node.id, EdgeKind.IMPORTS.value)
                if key not in existing_keys:
                    detector = "python.ast.reexport_import" if strategy == "package_reexport" else "python.ast.package_import_repair"
                    detail = (
                        "Resolved import %s through package re-export chain: %s"
                        % (binding.qualified_name, " -> ".join(chain))
                        if strategy == "package_reexport"
                        else "Resolved package-relative import %s to canonical symbol %s"
                        % (binding.qualified_name, target_qname)
                    )
                    graph.add_edge(
                        _edge(
                            module_node.id,
                            target_node.id,
                            EdgeKind.IMPORTS,
                            confidence,
                            detector,
                            detail,
                            SourceLocation(_relative(root, parsed_file.path), binding.line),
                            {"python_resolution": {"strategy": strategy, "alias_chain": chain}},
                        )
                    )
                    existing_keys.add(key)
                    import_edges_added += 1

                for edge in graph.outgoing(module_node.id):
                    if edge.kind != EdgeKind.IMPORTS:
                        continue
                    old_target = graph.node(edge.target)
                    if old_target is None or old_target.kind.value != "external_system":
                        continue
                    local_name = edge.attributes.get("local_name") if isinstance(edge.attributes, dict) else None
                    if old_target.qualified_name == binding.qualified_name or local_name == binding.local_name:
                        edges_to_remove.add(edge.id)

        for callable_node, source_qname in _iter_callables(parsed_file.module, parsed_file.tree):
            source_node = nodes_by_qname.get(source_qname)
            if source_node is None:
                continue
            collector = _ScopedCallCollector(callable_node)
            collector.visit(callable_node)
            for call in collector.calls:
                if not isinstance(call.func, ast.Name):
                    continue
                binding = parsed_file.imports.get(call.func.id)
                if binding is None:
                    continue
                resolved = _binding_resolution(binding.qualified_name, resolved_aliases, nodes_by_qname)
                if resolved is None:
                    continue
                target_qname, chain, confidence, strategy = resolved
                target_node = nodes_by_qname.get(target_qname)
                if target_node is None or target_node.kind.value == "module":
                    continue
                key = (source_node.id, target_node.id, EdgeKind.CALLS.value)
                if key in existing_keys:
                    _remove_unresolved(source_node, call.func.id)
                    continue
                line = getattr(call, "lineno", getattr(callable_node, "lineno", 1))
                detector = "python.ast.reexport_call" if strategy == "package_reexport" else "python.ast.imported_call_repair"
                detail = (
                    "Resolved call %s() through package re-export chain: %s"
                    % (call.func.id, " -> ".join(chain))
                    if strategy == "package_reexport"
                    else "Resolved imported call %s() to canonical symbol %s" % (call.func.id, target_qname)
                )
                graph.add_edge(
                    _edge(
                        source_node.id,
                        target_node.id,
                        EdgeKind.CALLS,
                        confidence,
                        detector,
                        detail,
                        SourceLocation(_relative(root, parsed_file.path), line),
                        {"python_resolution": {"strategy": strategy, "alias_chain": chain}},
                    )
                )
                existing_keys.add(key)
                call_edges_added += 1
                _remove_unresolved(source_node, call.func.id)

    if edges_to_remove:
        before = len(graph.edges)
        graph.edges = [edge for edge in graph.edges if edge.id not in edges_to_remove]
        repaired_external_import_edges = before - len(graph.edges)
        graph._reindex()
        _remove_orphan_externals(graph)

    graph.metadata["python_reexport_resolution"] = {
        "package_aliases": len(raw_aliases),
        "resolved_aliases": len(resolved_aliases),
        "ambiguous_aliases": len(ambiguous_aliases),
        "call_edges_added": call_edges_added,
        "import_edges_added": import_edges_added,
        "external_import_edges_repaired": repaired_external_import_edges,
        "strategy": "unique-static-alias-chain-only",
    }
    graph.validate()
    return graph


def _resolved_alias_index(
    parsed: Sequence[ParsedPythonFile],
    nodes_by_qname: Dict[str, SemanticNode],
) -> Tuple[Dict[str, ResolvedAlias], List[str]]:
    raw_aliases, explicit_exports = _package_aliases(parsed)
    resolved_aliases: Dict[str, ResolvedAlias] = {}
    ambiguous_aliases: List[str] = []
    for alias in sorted(raw_aliases):
        candidates = _resolve_alias(alias, raw_aliases, nodes_by_qname)
        canonical = {item[0] for item in candidates}
        if len(canonical) != 1:
            if candidates or len(raw_aliases.get(alias, set())) > 1:
                ambiguous_aliases.append(alias)
            continue
        target = next(iter(canonical))
        matching = [item for item in candidates if item[0] == target]
        matching.sort(key=lambda item: (len(item[1]), item[1]))
        chain = matching[0][1]
        confidence = 1.0 if all(step in explicit_exports for step in chain[:-1]) else 0.96
        resolved_aliases[alias] = (target, chain, confidence)
    return resolved_aliases, ambiguous_aliases


def _binding_resolution(
    qualified_name: str,
    resolved_aliases: Dict[str, ResolvedAlias],
    nodes_by_qname: Dict[str, SemanticNode],
) -> Optional[Tuple[str, List[str], float, str]]:
    direct = nodes_by_qname.get(qualified_name)
    if direct is not None:
        return qualified_name, [qualified_name], 1.0, "package_relative_import"
    resolved = resolved_aliases.get(qualified_name)
    if resolved is None:
        return None
    target, chain, confidence = resolved
    return target, chain, confidence, "package_reexport"


def _parse_python_files(root: Path) -> List[ParsedPythonFile]:
    result: List[ParsedPythonFile] = []
    for path in _iter_python_files(root):
        relative = _relative(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        is_package = path.name == "__init__.py"
        module = _module_name(root, path)
        imports = _collect_imports(tree, module, is_package)
        result.append(ParsedPythonFile(path, module, is_package, tree, imports))
    return result


def _package_aliases(parsed: Sequence[ParsedPythonFile]) -> Tuple[Dict[str, Set[str]], Set[str]]:
    aliases: Dict[str, Set[str]] = {}
    explicit_exports: Set[str] = set()
    for parsed_file in parsed:
        if not parsed_file.is_package:
            continue
        exported = _literal_all(parsed_file.tree)
        for binding in parsed_file.imports.values():
            if exported is not None and binding.local_name not in exported:
                continue
            if exported is None and binding.local_name.startswith("_"):
                continue
            alias = _qualify(parsed_file.module, binding.local_name)
            aliases.setdefault(alias, set()).add(binding.qualified_name)
            if exported is not None and binding.local_name in exported:
                explicit_exports.add(alias)
    return aliases, explicit_exports


def _resolve_alias(
    alias: str,
    raw_aliases: Dict[str, Set[str]],
    nodes_by_qname: Dict[str, SemanticNode],
) -> List[Tuple[str, List[str]]]:
    results: List[Tuple[str, List[str]]] = []

    def walk(current: str, chain: List[str], seen: Set[str]) -> None:
        if current in seen:
            return
        node = nodes_by_qname.get(current)
        if node is not None and node.kind.value != "module":
            results.append((current, chain + [current]))
            return
        targets = raw_aliases.get(current, set())
        if not targets:
            return
        next_seen = set(seen)
        next_seen.add(current)
        for target in sorted(targets):
            walk(target, chain + [current], next_seen)

    walk(alias, [], set())
    return results


def _collect_imports(tree: ast.Module, current_module: str, is_package: bool) -> Dict[str, ImportBinding]:
    imports: Dict[str, ImportBinding] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                qualified = alias.name if alias.asname else alias.name.split(".")[0]
                imports[local] = ImportBinding(local, qualified, getattr(node, "lineno", 1))
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_relative_module(current_module, node.module or "", node.level, is_package)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imports[local] = ImportBinding(local, _qualify(module, alias.name), getattr(node, "lineno", 1))
    return imports


def _literal_all(tree: ast.Module) -> Optional[Set[str]]:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            return None
        values: Set[str] = set()
        for element in node.value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return None
            values.add(element.value)
        return values
    return None


def _iter_callables(module: str, tree: ast.Module) -> Iterable[Tuple[ast.AST, str]]:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, _qualify(module, node.name)
        elif isinstance(node, ast.ClassDef):
            class_qname = _qualify(module, node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield child, "%s.%s" % (class_qname, child.name)


def _resolve_relative_module(current_module: str, module: str, level: int, is_package: bool) -> str:
    if level <= 0:
        return module
    package = current_module.split(".") if is_package else current_module.split(".")[:-1]
    ascend = max(0, level - 1)
    keep = max(0, len(package) - ascend)
    prefix = package[:keep]
    return ".".join(prefix + ([module] if module else []))


def _remove_unresolved(node: SemanticNode, raw_call: str) -> None:
    python = node.attributes.get("python", {})
    if not isinstance(python, dict):
        return
    unresolved = python.get("unresolved_calls")
    if not isinstance(unresolved, list):
        return
    filtered = [item for item in unresolved if str(item) != raw_call]
    if filtered:
        python["unresolved_calls"] = filtered
    else:
        python.pop("unresolved_calls", None)


def _remove_orphan_externals(graph: SemanticGraph) -> None:
    connected = {edge.source for edge in graph.edges} | {edge.target for edge in graph.edges}
    graph.nodes = [
        node
        for node in graph.nodes
        if not (node.kind.value == "external_system" and node.id not in connected)
    ]
    graph._reindex()


def _edge(
    source: str,
    target: str,
    kind: EdgeKind,
    confidence: float,
    detector: str,
    detail: str,
    location: SourceLocation,
    attributes: Dict[str, object],
) -> SemanticEdge:
    raw = "%s|%s|%s|%s|%s" % (source, target, kind.value, detector, location.line or "")
    evidence = Evidence(EvidenceKind.STATIC, detector, detail, location, confidence)
    return SemanticEdge(
        id="edge:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
        source=source,
        target=target,
        kind=kind,
        confidence=confidence,
        evidence=[evidence],
        attributes=attributes,
    )


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or root.name


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        yield path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _qualify(module: str, name: str) -> str:
    return "%s.%s" % (module, name) if module else name