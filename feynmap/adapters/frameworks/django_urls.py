"""P1.4: conservative, source-backed Django named URL registration and reversal.

Static source is parsed, never imported or executed. URL names are kept separate
from literal HTTP paths: reverse() and template {% url %} refer to a named
registration, not to an HTTP client request with template text as its URL.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import add_contract
from feynmap.adapters.python_source import get_python_source_session
from ._python import _CallableLineIndex, _expr_name, _string


DJANGO_ROUTE_FUNCTIONS = {"django.urls.path", "django.urls.re_path"}
DJANGO_REVERSE_FUNCTIONS = {
    "django.urls.reverse", "django.urls.reverse_lazy",
    "django.core.urlresolvers.reverse", "django.core.urlresolvers.reverse_lazy",
}
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)*$")


def _module_name(relative: str) -> str:
    parts = list(PurePosixPath(relative).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(tree: ast.Module, module: str, is_package: bool) -> Dict[str, str]:
    """Resolve only explicit import bindings; no short-name repository guessing."""
    bindings: Dict[str, str] = {}
    package = module.split(".") if is_package else module.split(".")[:-1]
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    first = alias.name.split(".")[0]
                    bindings[first] = first
        elif isinstance(statement, ast.ImportFrom):
            if statement.level:
                keep = len(package) - (statement.level - 1)
                if keep < 0:
                    continue
                prefix = package[:keep]
                target = ".".join(prefix + ([statement.module] if statement.module else []))
            else:
                target = statement.module or ""
            for alias in statement.names:
                if alias.name == "*":
                    continue
                bindings[alias.asname or alias.name] = (
                    target + "." + alias.name if target else alias.name
                )
    return bindings


def _resolve(expr: ast.AST, module: str, imports: Dict[str, str]) -> str:
    name = _expr_name(expr)
    if not name:
        return ""
    parts = name.split(".")
    binding = imports.get(parts[0])
    if binding:
        return ".".join([binding] + parts[1:])
    return module + "." + name if module else name


def _assigned_string(tree: ast.Module, variable: str) -> Optional[str]:
    value = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == variable
            for target in statement.targets
        ):
            value = _string(statement.value)
    return value


def _keyword(call: ast.Call, name: str) -> Optional[ast.AST]:
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


@dataclass
class _Pattern:
    source_file: str
    line: int
    route: str
    kind: str
    name: Optional[str] = None
    handler: str = ""
    include: str = ""
    include_namespace: Optional[str] = None
    include_app: Optional[str] = None


@dataclass
class _URLModule:
    name: str
    relative: str
    app_name: Optional[str]
    patterns: List[_Pattern]


def _pattern_calls(tree: ast.Module) -> List[ast.Call]:
    """Only inspect declared static urlpatterns, not arbitrary path() calls."""
    result: List[ast.Call] = []
    for statement in tree.body:
        value = None
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "urlpatterns"
            for target in statement.targets
        ):
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and (
            isinstance(statement.target, ast.Name)
            and statement.target.id == "urlpatterns"
        ):
            value = statement.value
        elif isinstance(statement, ast.AugAssign) and (
            isinstance(statement.target, ast.Name)
            and statement.target.id == "urlpatterns"
            and isinstance(statement.op, ast.Add)
        ):
            value = statement.value
        if isinstance(value, (ast.List, ast.Tuple)):
            result.extend(item for item in value.elts if isinstance(item, ast.Call))
    return result


def _include_reference(
    call: ast.Call, module: str, imports: Dict[str, str]
) -> Tuple[str, Optional[str], Optional[str]]:
    if not call.args:
        return "", None, None
    target = call.args[0]
    app_name = None
    if isinstance(target, ast.Tuple) and len(target.elts) == 2:
        app_name = _string(target.elts[1])
        target = target.elts[0]
    reference = _string(target)
    if reference is None and isinstance(target, (ast.Name, ast.Attribute)):
        reference = _resolve(target, module, imports)
    namespace_ast = _keyword(call, "namespace")
    namespace = _string(namespace_ast) if namespace_ast is not None else None
    # Dynamic namespace is not a statically resolvable registration.
    if namespace_ast is not None and namespace is None:
        return "", None, None
    return reference or "", namespace, app_name


def _extract_modules(root: Path) -> Tuple[Dict[str, _URLModule], List[dict]]:
    source = get_python_source_session(root)
    modules: Dict[str, _URLModule] = {}
    unresolved: List[dict] = []
    for record in source.records():
        if record.path.name != "urls.py" or record.tree is None:
            continue
        module = _module_name(record.relative)
        imports = _imports(record.tree, module, False)
        patterns: List[_Pattern] = []
        for call in _pattern_calls(record.tree):
            operation = _resolve(call.func, module, imports)
            if operation not in DJANGO_ROUTE_FUNCTIONS or len(call.args) < 2:
                continue
            route = _string(call.args[0])
            if route is None:
                unresolved.append({
                    "source_file": record.relative, "line": call.lineno,
                    "reason": "dynamic_route",
                })
                continue
            name_ast = _keyword(call, "name")
            name = _string(name_ast) if name_ast is not None else None
            target = call.args[1]
            if (
                isinstance(target, ast.Call)
                and _resolve(target.func, module, imports) == "django.urls.include"
            ):
                included, namespace, app_name = _include_reference(target, module, imports)
                if not included:
                    unresolved.append({
                        "source_file": record.relative, "line": call.lineno,
                        "reason": "dynamic_or_unsupported_include",
                    })
                    continue
                patterns.append(_Pattern(
                    record.relative, call.lineno, route, operation.rsplit(".", 1)[-1],
                    include=included, include_namespace=namespace, include_app=app_name,
                ))
                continue
            if name_ast is not None and name is None:
                unresolved.append({
                    "source_file": record.relative, "line": call.lineno,
                    "reason": "dynamic_name",
                })
            if isinstance(target, ast.Call) and (
                isinstance(target.func, ast.Attribute) and target.func.attr == "as_view"
            ):
                target = target.func.value
            handler = (
                _resolve(target, module, imports)
                if isinstance(target, (ast.Name, ast.Attribute)) else ""
            )
            if not handler:
                unresolved.append({
                    "source_file": record.relative, "line": call.lineno,
                    "reason": "dynamic_handler",
                })
                continue
            patterns.append(_Pattern(
                record.relative, call.lineno, route, operation.rsplit(".", 1)[-1],
                name=name, handler=handler,
            ))
        modules[module] = _URLModule(
            module, record.relative, _assigned_string(record.tree, "app_name"), patterns,
        )
    return modules, unresolved


def _join_route(prefix: str, suffix: str) -> str:
    return "/" + (prefix + suffix).lstrip("/")


def _registrations(modules: Dict[str, _URLModule], unresolved: List[dict]) -> List[dict]:
    included = {
        item.include
        for module in modules.values()
        for item in module.patterns if item.include in modules
    }
    roots = sorted(name for name in modules if name not in included)
    if not roots:
        roots = sorted(modules)
    registered: List[dict] = []

    def walk(name: str, prefix: str, namespaces: Tuple[str, ...],
             stack: Tuple[str, ...]) -> None:
        if name in stack:
            unresolved.append({"module": name, "reason": "cyclic_url_include"})
            return
        urlconf = modules.get(name)
        if urlconf is None:
            unresolved.append({"module": name, "reason": "missing_included_urlconf"})
            return
        for pattern in urlconf.patterns:
            route = _join_route(prefix, pattern.route)
            if pattern.include:
                child = modules.get(pattern.include)
                if child is None:
                    unresolved.append({
                        "source_file": pattern.source_file, "line": pattern.line,
                        "reason": "missing_included_urlconf", "module": pattern.include,
                    })
                    continue
                # Django uses the included app_name as its default instance
                # namespace. An explicit namespace without app_name is invalid.
                app = pattern.include_app or child.app_name
                namespace = pattern.include_namespace or app
                if pattern.include_namespace and not app:
                    unresolved.append({
                        "source_file": pattern.source_file, "line": pattern.line,
                        "reason": "namespace_without_app_name",
                    })
                    continue
                if not NAME_RE.fullmatch(namespace or "") and namespace:
                    unresolved.append({
                        "source_file": pattern.source_file, "line": pattern.line,
                        "reason": "invalid_namespace",
                    })
                    continue
                walk(pattern.include, prefix + pattern.route,
                     namespaces + ((namespace,) if namespace else ()), stack + (name,))
                continue
            qualified = ":".join(namespaces + (pattern.name,)) if pattern.name else ""
            registered.append({
                "source_file": pattern.source_file, "line": pattern.line,
                "handler": pattern.handler, "target": route,
                "name": pattern.name, "route_name": qualified,
                "namespace": ":".join(namespaces),
                "pattern_kind": pattern.kind,
                "registration_root": stack[0] if stack else name,
            })

    for module in roots:
        walk(module, "", (), ())
    return registered


def _reverse_calls(graph: SemanticGraph, root: Path, unresolved: List[dict]) -> None:
    source = get_python_source_session(root)
    index = _CallableLineIndex(graph)
    for record in source.records():
        if record.tree is None:
            continue
        module = _module_name(record.relative)
        imports = _imports(record.tree, module, record.path.name == "__init__.py")
        calls = source.ast_index(record.path).calls
        owners = index.resolve_many(record.relative, [
            getattr(call, "lineno", 1) for call in calls
        ])
        for call in calls:
            operation = _resolve(call.func, module, imports)
            if operation not in DJANGO_REVERSE_FUNCTIONS:
                continue
            arg = call.args[0] if call.args else _keyword(call, "viewname")
            owner = owners.get(call.lineno)
            if not owner:
                continue
            value = _string(arg) if arg is not None else None
            if not value or not NAME_RE.fullmatch(value):
                unresolved.append({
                    "source_file": record.relative, "line": call.lineno,
                    "source_node_id": owner.id, "reason": "dynamic_or_invalid_reverse_name",
                })
                continue
            add_contract(
                owner, "django_url_reverse", value, 0.98,
                syntax="python", api=operation.rsplit(".", 1)[-1],
                source_file=record.relative, line=call.lineno,
                evidence_kind="static", derivation="django.reverse.literal",
            )


def enrich_django_named_urls(graph: SemanticGraph, root: Path) -> None:
    """Attach exact static named registrations and Python reversal contracts.

    Every URL registration is traced through static include() composition. A
    handler must resolve by fully qualified, imported identity, not by a
    repository-global short name. Unknown registrations are recorded rather
    than guessed. HTML-side {% url %} references are resolved after graph merge.
    """
    modules, unresolved = _extract_modules(root)
    registrations = _registrations(modules, unresolved)
    handlers: Dict[str, List[SemanticNode]] = {}
    for node in graph.nodes:
        if node.language == "python" and node.kind in {
            NodeKind.HANDLER, NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS,
        }:
            handlers.setdefault(node.qualified_name, []).append(node)
    accepted: List[dict] = []
    for item in registrations:
        matches = handlers.get(item["handler"], [])
        if len(matches) != 1:
            unresolved.append({
                "source_file": item["source_file"], "line": item["line"],
                "reason": "missing_or_ambiguous_imported_handler",
                "handler": item["handler"], "route_name": item["route_name"],
            })
            continue
        handler = matches[0]
        fields = {
            "methods": ["ANY"], "framework": "django",
            "source_file": item["source_file"], "source_line": item["line"],
            "pattern_kind": item["pattern_kind"],
            "derivation": "django.urls.static_registration",
            "evidence_kind": "static",
        }
        if item["name"]:
            fields.update(
                name=item["name"], route_name=item["route_name"],
                url_name=item["route_name"], namespace=item["namespace"],
            )
        add_contract(handler, "http_server", item["target"], 0.98, **fields)
        accepted.append(dict(item, handler_node_id=handler.id))

    _reverse_calls(graph, root, unresolved)
    graph.metadata["django_named_urls"] = {
        "version": "1.0.0",
        "registrations": accepted,
        "unresolved": unresolved,
    }
