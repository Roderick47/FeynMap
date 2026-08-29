"""Additional generic Python resolution based on local type/constructor evidence.

This pass stays framework-neutral. It resolves calls such as
``self.resolver.resolve()`` only when the repository contains enough static
evidence to identify exactly one possible type for ``self.resolver``.

Package re-export evidence is also consumed. For example, an annotation imported
as ``from feynmap.adapters import AdapterRegistry`` can be grounded to the
canonical ``feynmap.adapters.base.AdapterRegistry`` definition before resolving
``self.registry.detect_languages()``.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation

from .python_reexports import ResolvedAlias, python_reexport_aliases


EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
OPTIONAL_WRAPPERS = {"Optional", "Union", "Annotated"}
CLASS_KINDS = {"class", "data_model", "service", "handler", "transformer", "middleware"}


@dataclass(frozen=True)
class ResolvedType:
    qualified_name: str
    alias_chain: Tuple[str, ...] = ()
    confidence: float = 1.0


class _MethodCallCollector(ast.NodeVisitor):
    """Collect calls from one method without descending into nested callables."""

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


def enrich_python_attribute_calls(graph: SemanticGraph, project_path: Path) -> SemanticGraph:
    """Resolve statically provable ``self.attribute.method()`` calls.

    A relationship is added only when constructor/annotation evidence produces
    exactly one method target. Re-export aliases may ground the type, but cycles
    or ambiguous aliases remain unresolved.
    """
    root = project_path.resolve()
    nodes_by_qname: Dict[str, SemanticNode] = {
        node.qualified_name: node
        for node in graph.nodes
        if node.language == "python" and node.qualified_name
    }
    if not nodes_by_qname:
        return graph

    reexport_aliases = python_reexport_aliases(graph, root)
    parsed: List[Tuple[Path, str, ast.Module, Dict[str, str]]] = []
    for path in _iter_python_files(root):
        relative = _relative(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        module = _module_name(root, path)
        parsed.append((path, module, tree, _collect_imports(tree, module)))

    attribute_types: Dict[str, Dict[str, Dict[str, ResolvedType]]] = {}
    for path, module, tree, imports in parsed:
        for class_node in (item for item in tree.body if isinstance(item, ast.ClassDef)):
            class_qname = _qualify(module, class_node.name)
            init = next(
                (
                    item
                    for item in class_node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
                ),
                None,
            )
            if init is None:
                continue
            inferred = _infer_instance_attributes(init, module, imports, nodes_by_qname, reexport_aliases)
            if inferred:
                attribute_types[class_qname] = inferred

    existing = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
    edges_added = 0
    alias_grounded_edges = 0
    for path, module, tree, imports in parsed:
        relative = _relative(root, path)
        for class_node in (item for item in tree.body if isinstance(item, ast.ClassDef)):
            class_qname = _qualify(module, class_node.name)
            class_attrs = attribute_types.get(class_qname, {})
            if not class_attrs:
                continue
            for method in class_node.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                source_qname = "%s.%s" % (class_qname, method.name)
                source_node = nodes_by_qname.get(source_qname)
                if source_node is None:
                    continue
                collector = _MethodCallCollector(method)
                collector.visit(method)
                for call in collector.calls:
                    parsed_call = _self_attribute_method(call.func)
                    if parsed_call is None:
                        continue
                    attribute, method_name = parsed_call
                    candidate_types = class_attrs.get(attribute, {})
                    target_records: List[Tuple[SemanticNode, ResolvedType]] = []
                    for candidate_type in sorted(candidate_types):
                        target = nodes_by_qname.get("%s.%s" % (candidate_type, method_name))
                        if target is not None:
                            target_records.append((target, candidate_types[candidate_type]))
                    unique_targets = {node.id: (node, type_info) for node, type_info in target_records}
                    if len(unique_targets) != 1:
                        continue
                    target_node, type_info = next(iter(unique_targets.values()))
                    key = (source_node.id, target_node.id, EdgeKind.CALLS.value)
                    if key in existing:
                        _remove_unresolved(source_node, "self.%s.%s" % (attribute, method_name))
                        continue
                    line = getattr(call, "lineno", getattr(method, "lineno", 1))
                    raw = "%s|%s|attribute-call|%s" % (source_node.id, target_node.id, line)
                    confidence = min(0.98, type_info.confidence)
                    alias_chain = list(type_info.alias_chain)
                    strategy = "instance_attribute_type_reexport" if alias_chain else "instance_attribute_type"
                    detail = "Resolved self.%s.%s() from unique constructor/annotation type evidence: %s" % (
                        attribute,
                        method_name,
                        type_info.qualified_name,
                    )
                    if alias_chain:
                        detail += " via package re-export chain: %s" % " -> ".join(alias_chain)
                    evidence = Evidence(
                        EvidenceKind.STATIC,
                        "python.ast.instance_attribute_call",
                        detail,
                        SourceLocation(relative, line),
                        confidence,
                    )
                    graph.add_edge(
                        SemanticEdge(
                            id="edge:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
                            source=source_node.id,
                            target=target_node.id,
                            kind=EdgeKind.CALLS,
                            confidence=confidence,
                            evidence=[evidence],
                            attributes={
                                "python_resolution": {
                                    "strategy": strategy,
                                    "attribute": attribute,
                                    "candidate_types": sorted(candidate_types),
                                    "type_alias_chain": alias_chain,
                                }
                            },
                        )
                    )
                    existing.add(key)
                    edges_added += 1
                    if alias_chain:
                        alias_grounded_edges += 1
                    _remove_unresolved(source_node, "self.%s.%s" % (attribute, method_name))

    graph.metadata["python_attribute_resolution"] = {
        "classes_with_typed_attributes": len(attribute_types),
        "reexport_aliases_consulted": len(reexport_aliases),
        "call_edges_added": edges_added,
        "alias_grounded_call_edges": alias_grounded_edges,
        "strategy": "unique-static-type-only",
    }
    graph.validate()
    return graph


def _infer_instance_attributes(
    init: ast.AST,
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
    reexport_aliases: Dict[str, ResolvedAlias],
) -> Dict[str, Dict[str, ResolvedType]]:
    parameter_types: Dict[str, Dict[str, ResolvedType]] = {}
    args = getattr(init, "args", None)
    if args is not None:
        parameters = list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs)
        for parameter in parameters:
            if parameter.arg in {"self", "cls"}:
                continue
            parameter_types[parameter.arg] = _annotation_type_candidates(
                getattr(parameter, "annotation", None), module, imports, nodes_by_qname, reexport_aliases
            )

    result: Dict[str, Dict[str, ResolvedType]] = {}
    for statement in getattr(init, "body", []):
        targets_and_values: List[Tuple[ast.AST, Optional[ast.AST], Optional[ast.AST]]] = []
        if isinstance(statement, ast.Assign):
            targets_and_values.extend((target, statement.value, None) for target in statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets_and_values.append((statement.target, statement.value, statement.annotation))
        else:
            continue

        for target, value, annotation in targets_and_values:
            attribute = _self_attribute_name(target)
            if not attribute:
                continue
            candidates: Dict[str, ResolvedType] = {}
            _merge_type_candidates(
                candidates,
                _annotation_type_candidates(annotation, module, imports, nodes_by_qname, reexport_aliases),
            )
            _merge_type_candidates(
                candidates,
                _value_type_candidates(value, module, imports, nodes_by_qname, parameter_types, reexport_aliases),
            )
            if candidates:
                bucket = result.setdefault(attribute, {})
                _merge_type_candidates(bucket, candidates)
    return result


def _annotation_type_candidates(
    node: Optional[ast.AST],
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
    reexport_aliases: Dict[str, ResolvedAlias],
) -> Dict[str, ResolvedType]:
    if node is None:
        return {}
    index_type = getattr(ast, "Index", None)
    if index_type is not None and isinstance(node, index_type):
        return _annotation_type_candidates(node.value, module, imports, nodes_by_qname, reexport_aliases)
    if isinstance(node, (ast.Name, ast.Attribute)):
        resolved = _resolve_class_name(_render_expr(node), module, imports, nodes_by_qname, reexport_aliases)
        return {resolved.qualified_name: resolved} if resolved else {}
    if isinstance(node, ast.Subscript):
        wrapper = _render_expr(node.value).rsplit(".", 1)[-1]
        if wrapper not in OPTIONAL_WRAPPERS:
            return {}
        return _annotation_type_candidates(node.slice, module, imports, nodes_by_qname, reexport_aliases)
    if isinstance(node, (ast.Tuple, ast.List)):
        result: Dict[str, ResolvedType] = {}
        for item in node.elts:
            _merge_type_candidates(
                result,
                _annotation_type_candidates(item, module, imports, nodes_by_qname, reexport_aliases),
            )
        return result
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        result: Dict[str, ResolvedType] = {}
        _merge_type_candidates(
            result,
            _annotation_type_candidates(node.left, module, imports, nodes_by_qname, reexport_aliases),
        )
        _merge_type_candidates(
            result,
            _annotation_type_candidates(node.right, module, imports, nodes_by_qname, reexport_aliases),
        )
        return result
    return {}


def _value_type_candidates(
    node: Optional[ast.AST],
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
    parameter_types: Dict[str, Dict[str, ResolvedType]],
    reexport_aliases: Dict[str, ResolvedAlias],
) -> Dict[str, ResolvedType]:
    if node is None:
        return {}
    if isinstance(node, ast.Name):
        return dict(parameter_types.get(node.id, {}))
    if isinstance(node, ast.Call):
        resolved = _resolve_class_name(_render_expr(node.func), module, imports, nodes_by_qname, reexport_aliases)
        return {resolved.qualified_name: resolved} if resolved else {}
    if isinstance(node, ast.BoolOp):
        result: Dict[str, ResolvedType] = {}
        for value in node.values:
            _merge_type_candidates(
                result,
                _value_type_candidates(value, module, imports, nodes_by_qname, parameter_types, reexport_aliases),
            )
        return result
    if isinstance(node, ast.IfExp):
        result: Dict[str, ResolvedType] = {}
        _merge_type_candidates(
            result,
            _value_type_candidates(node.body, module, imports, nodes_by_qname, parameter_types, reexport_aliases),
        )
        _merge_type_candidates(
            result,
            _value_type_candidates(node.orelse, module, imports, nodes_by_qname, parameter_types, reexport_aliases),
        )
        return result
    return {}


def _resolve_class_name(
    raw: str,
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
    reexport_aliases: Dict[str, ResolvedAlias],
) -> Optional[ResolvedType]:
    if not raw or raw in {"None", "NoneType"}:
        return None
    candidates: List[str] = []
    if "." not in raw:
        candidates.append(_qualify(module, raw))
        imported = imports.get(raw)
        if imported:
            candidates.append(imported)
    else:
        head, tail = raw.split(".", 1)
        imported = imports.get(head)
        if imported:
            candidates.append("%s.%s" % (imported, tail))
        candidates.append(raw)

    for candidate in candidates:
        node = nodes_by_qname.get(candidate)
        if node is not None and node.kind.value in CLASS_KINDS:
            return ResolvedType(candidate)
        alias = reexport_aliases.get(candidate)
        if alias is None:
            continue
        target, chain, confidence = alias
        target_node = nodes_by_qname.get(target)
        if target_node is not None and target_node.kind.value in CLASS_KINDS:
            return ResolvedType(target, tuple(chain), confidence)
    return None


def _merge_type_candidates(target: Dict[str, ResolvedType], incoming: Dict[str, ResolvedType]) -> None:
    for qualified_name, candidate in incoming.items():
        current = target.get(qualified_name)
        if current is None:
            target[qualified_name] = candidate
            continue
        if candidate.confidence > current.confidence:
            target[qualified_name] = candidate
            continue
        if candidate.confidence == current.confidence and len(candidate.alias_chain) < len(current.alias_chain):
            target[qualified_name] = candidate


def _self_attribute_method(node: ast.AST) -> Optional[Tuple[str, str]]:
    if not isinstance(node, ast.Attribute):
        return None
    owner = node.value
    if not isinstance(owner, ast.Attribute):
        return None
    if not isinstance(owner.value, ast.Name) or owner.value.id != "self":
        return None
    return owner.attr, node.attr


def _self_attribute_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


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


def _collect_imports(tree: ast.Module, current_module: str) -> Dict[str, str]:
    imports: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imports[local] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_relative_module(current_module, node.module or "", node.level)
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports[alias.asname or alias.name] = _qualify(module, alias.name)
    return imports


def _resolve_relative_module(current_module: str, module: str, level: int) -> str:
    if level <= 0:
        return module
    package = current_module.split(".")[:-1]
    keep = max(0, len(package) - (level - 1))
    prefix = package[:keep]
    return ".".join(prefix + ([module] if module else []))


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
    if isinstance(node, ast.Subscript):
        return _render_expr(node.value)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return node.__class__.__name__