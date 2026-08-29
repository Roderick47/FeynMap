"""Additional generic Python resolution based on local type/constructor evidence.

This pass stays framework-neutral. It resolves calls such as
``self.resolver.resolve()`` only when the repository contains enough static
evidence to identify exactly one possible type for ``self.resolver``.

The first use case is FeynMap's own ``FeynMapEngine``: ``self.resolver`` is
assigned from an ``Optional[IntegrationResolver]`` parameter or from an
``IntegrationResolver()`` constructor. That evidence is sufficient to connect
``FeynMapEngine.analyze`` to ``IntegrationResolver.resolve`` without guessing.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from feynmap.core import EdgeKind, Evidence, EvidenceKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation


EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
OPTIONAL_WRAPPERS = {"Optional", "Union", "Annotated"}


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

    A relationship is added only when attribute evidence produces exactly one
    method target. Multiple candidate target types are intentionally left
    unresolved.
    """
    root = project_path.resolve()
    nodes_by_qname: Dict[str, SemanticNode] = {
        node.qualified_name: node
        for node in graph.nodes
        if node.language == "python" and node.qualified_name
    }
    if not nodes_by_qname:
        return graph

    parsed: List[Tuple[Path, str, ast.Module, Dict[str, str]]] = []
    for path in _iter_python_files(root):
        relative = _relative(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        module = _module_name(root, path)
        parsed.append((path, module, tree, _collect_imports(tree, module)))

    attribute_types: Dict[str, Dict[str, Set[str]]] = {}
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
            inferred = _infer_instance_attributes(init, module, imports, nodes_by_qname)
            if inferred:
                attribute_types[class_qname] = inferred

    existing = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
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
                    candidate_types = class_attrs.get(attribute, set())
                    target_nodes = []
                    for candidate_type in sorted(candidate_types):
                        target = nodes_by_qname.get("%s.%s" % (candidate_type, method_name))
                        if target is not None:
                            target_nodes.append(target)
                    unique_targets = {node.id: node for node in target_nodes}
                    if len(unique_targets) != 1:
                        continue
                    target_node = next(iter(unique_targets.values()))
                    key = (source_node.id, target_node.id, EdgeKind.CALLS.value)
                    if key in existing:
                        _remove_unresolved(source_node, "self.%s.%s" % (attribute, method_name))
                        continue
                    line = getattr(call, "lineno", getattr(method, "lineno", 1))
                    raw = "%s|%s|attribute-call|%s" % (source_node.id, target_node.id, line)
                    evidence = Evidence(
                        EvidenceKind.STATIC,
                        "python.ast.instance_attribute_call",
                        "Resolved self.%s.%s() from unique constructor/annotation type evidence: %s"
                        % (attribute, method_name, ", ".join(sorted(candidate_types))),
                        SourceLocation(relative, line),
                        0.98,
                    )
                    graph.add_edge(
                        SemanticEdge(
                            id="edge:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
                            source=source_node.id,
                            target=target_node.id,
                            kind=EdgeKind.CALLS,
                            confidence=0.98,
                            evidence=[evidence],
                            attributes={
                                "python_resolution": {
                                    "strategy": "instance_attribute_type",
                                    "attribute": attribute,
                                    "candidate_types": sorted(candidate_types),
                                }
                            },
                        )
                    )
                    existing.add(key)
                    _remove_unresolved(source_node, "self.%s.%s" % (attribute, method_name))

    graph.metadata["python_attribute_resolution"] = {
        "classes_with_typed_attributes": len(attribute_types),
        "strategy": "unique-static-type-only",
    }
    graph.validate()
    return graph


def _infer_instance_attributes(
    init: ast.AST,
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
) -> Dict[str, Set[str]]:
    parameter_types: Dict[str, Set[str]] = {}
    args = getattr(init, "args", None)
    if args is not None:
        parameters = list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs)
        for parameter in parameters:
            if parameter.arg in {"self", "cls"}:
                continue
            parameter_types[parameter.arg] = _annotation_type_candidates(
                getattr(parameter, "annotation", None), module, imports, nodes_by_qname
            )

    result: Dict[str, Set[str]] = {}
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
            candidates = set()
            candidates.update(_annotation_type_candidates(annotation, module, imports, nodes_by_qname))
            candidates.update(_value_type_candidates(value, module, imports, nodes_by_qname, parameter_types))
            if candidates:
                result.setdefault(attribute, set()).update(candidates)
    return result


def _annotation_type_candidates(
    node: Optional[ast.AST],
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
) -> Set[str]:
    if node is None:
        return set()
    if isinstance(node, (ast.Name, ast.Attribute)):
        resolved = _resolve_class_name(_render_expr(node), module, imports, nodes_by_qname)
        return {resolved} if resolved else set()
    if isinstance(node, ast.Subscript):
        wrapper = _render_expr(node.value).rsplit(".", 1)[-1]
        if wrapper not in OPTIONAL_WRAPPERS:
            return set()
        return _annotation_type_candidates(node.slice, module, imports, nodes_by_qname)
    if isinstance(node, (ast.Tuple, ast.List)):
        result: Set[str] = set()
        for item in node.elts:
            result.update(_annotation_type_candidates(item, module, imports, nodes_by_qname))
        return result
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_type_candidates(node.left, module, imports, nodes_by_qname) | _annotation_type_candidates(
            node.right, module, imports, nodes_by_qname
        )
    return set()


def _value_type_candidates(
    node: Optional[ast.AST],
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
    parameter_types: Dict[str, Set[str]],
) -> Set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return set(parameter_types.get(node.id, set()))
    if isinstance(node, ast.Call):
        resolved = _resolve_class_name(_render_expr(node.func), module, imports, nodes_by_qname)
        return {resolved} if resolved else set()
    if isinstance(node, ast.BoolOp):
        result: Set[str] = set()
        for value in node.values:
            result.update(_value_type_candidates(value, module, imports, nodes_by_qname, parameter_types))
        return result
    if isinstance(node, ast.IfExp):
        return _value_type_candidates(node.body, module, imports, nodes_by_qname, parameter_types) | _value_type_candidates(
            node.orelse, module, imports, nodes_by_qname, parameter_types
        )
    return set()


def _resolve_class_name(
    raw: str,
    module: str,
    imports: Dict[str, str],
    nodes_by_qname: Dict[str, SemanticNode],
) -> Optional[str]:
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
        if node is not None and node.kind.value in {"class", "data_model", "service", "handler", "transformer", "middleware"}:
            return candidate
    return None


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
