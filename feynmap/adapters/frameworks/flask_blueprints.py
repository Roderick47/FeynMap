"""P1.5: static Flask Blueprint declaration/registration/route composition.

Declared @bp.route('/x') is not evidence of an exposed /x endpoint. Only
a source-resolved registration on a Flask app (possibly via nested Blueprint)
produces an HTTP server contract. No third-party modules are imported/executed.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from feynmap.adapters.python_source import get_python_source_session
from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import add_contract
from ._python import _CallableLineIndex, _expr_name, _string, mark_role

ROUTE_METHODS = {
    "get": ["GET"], "post": ["POST"], "put": ["PUT"], "patch": ["PATCH"],
    "delete": ["DELETE"], "options": ["OPTIONS"], "head": ["HEAD"],
}


def _module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/") if hasattr(str, "removesuffix") else path[:-3].split("/")
    # Keep the parser/adapter compatible with Python 3.8.
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(statements: list, module: str, package: bool) -> Dict[str, str]:
    result: Dict[str, str] = {}
    parent = module.split(".") if package else module.split(".")[:-1]
    for item in statements:
        if isinstance(item, ast.Import):
            for alias in item.names:
                if alias.asname:
                    result[alias.asname] = alias.name
                else:
                    first = alias.name.split(".")[0]
                    result[first] = first
        elif isinstance(item, ast.ImportFrom):
            if item.level:
                keep = len(parent) - (item.level - 1)
                if keep < 0:
                    continue
                prefix = parent[:keep]
                target = ".".join(prefix + ([item.module] if item.module else []))
            else:
                target = item.module or ""
            for alias in item.names:
                if alias.name == "*":
                    continue
                result[alias.asname or alias.name] = (
                    (target + "." if target else "") + alias.name
                )
    return result


def _identity(expr: ast.AST, module: str, imports: Dict[str, str]) -> str:
    name = _expr_name(expr)
    if not name:
        return ""
    parts = name.split(".")
    binding = imports.get(parts[0])
    if binding:
        return ".".join([binding] + parts[1:])
    return module + "." + name if module else name


def _kw(call: ast.Call, key: str) -> Optional[ast.AST]:
    return next((item.value for item in call.keywords if item.arg == key), None)


def _literal_prefix(call: ast.Call) -> Tuple[str, bool, bool]:
    """(prefix, valid_static_value, explicitly_passed). None uses default."""
    arg = _kw(call, "url_prefix")
    if arg is None:
        return "", True, False
    if isinstance(arg, ast.Constant) and arg.value is None:
        return "", True, False
    value = _string(arg)
    if value is None or (value and not value.startswith("/")):
        return "", False, True
    return value or "", True, True


def _join(prefix: str, fragment: str) -> str:
    if fragment == "/":
        return (prefix.rstrip("/") + "/") if prefix else "/"
    return (prefix.rstrip("/") + "/" + fragment.lstrip("/")) or "/"


def _route_args(call: ast.Call, operation: str) -> Tuple[Optional[str], Optional[List[str]]]:
    first = call.args[0] if call.args else _kw(call, "rule")
    rule = _string(first) if first is not None else None
    if not rule or not rule.startswith("/"):
        return None, None
    if operation in ROUTE_METHODS:
        return rule, list(ROUTE_METHODS[operation])
    methods = _kw(call, "methods")
    if methods is None:
        return rule, ["GET"]
    if not isinstance(methods, (ast.List, ast.Tuple, ast.Set)):
        return rule, None
    values = [_string(item) for item in methods.elts]
    if not values or any(
        item is None or item.upper() not in
        {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
        for item in values
    ):
        return rule, None
    return rule, sorted(set(item.upper() for item in values))


def _assignments(statements: list, module: str, imports: Dict[str, str],
                 constructor: str) -> List[Tuple[str, ast.Call]]:
    result = []
    for item in statements:
        value = None
        targets = []
        if isinstance(item, ast.Assign):
            value = item.value
            targets = item.targets
        elif isinstance(item, ast.AnnAssign):
            value = item.value
            targets = [item.target]
        if isinstance(value, ast.Call) and _identity(value.func, module, imports) == constructor:
            for target in targets:
                if isinstance(target, ast.Name):
                    result.append((target.id, value))
    return result


def _calls_in_scope(statements: list) -> List[ast.Call]:
    """Calls in a lexical scope, excluding nested function/class declarations."""
    result = []
    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.Call):
            result.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
    for item in statements:
        visit(item)
    return result


def _collect_declarations(source, unresolved: List[dict]) -> Dict[str, dict]:
    declared: Dict[str, dict] = {}
    for record in source.records():
        if record.tree is None:
            continue
        module = _module_name(record.relative)
        imports = _imports(record.tree.body, module,
                           record.relative.endswith("/__init__.py"))
        for variable, call in _assignments(record.tree.body, module, imports,
                                            "flask.Blueprint"):
            name = _string(call.args[0]) if call.args else None
            prefix, valid, _ = _literal_prefix(call)
            if not name or not valid:
                unresolved.append({
                    "source_file": record.relative, "line": call.lineno,
                    "reason": "dynamic_blueprint_name_or_default_prefix",
                    "identity": module + "." + variable,
                })
                continue
            declared[module + "." + variable] = {
                "identity": module + "." + variable, "name": name,
                "default_prefix": prefix, "declaration_file": record.relative,
                "declaration_line": call.lineno,
            }
    return declared


def _registrations(source, blueprints: Dict[str, dict],
                   unresolved: List[dict]) -> List[dict]:
    registrations = []
    for record in source.records():
        if record.tree is None:
            continue
        module = _module_name(record.relative)
        global_imports = _imports(record.tree.body, module,
                                  record.relative.endswith("/__init__.py"))
        scopes = [("<module>", record.tree.body, global_imports)]
        for item in record.tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                imports = dict(global_imports)
                imports.update(_imports(item.body, module, False))
                scopes.append((item.name, item.body, imports))

        for scope, statements, imports in scopes:
            app_objects = {
                local for local, _ in _assignments(
                    statements, module, imports, "flask.Flask"
                )
            }
            for call in _calls_in_scope(statements):
                if (
                    not isinstance(call.func, ast.Attribute)
                    or call.func.attr != "register_blueprint"
                    or not call.args
                ):
                    continue
                host = call.func.value
                local_host = _expr_name(host)
                if local_host in app_objects:
                    parent = None
                    host_kind = "flask_application"
                else:
                    parent = _identity(host, module, imports)
                    if parent not in blueprints:
                        continue
                    host_kind = "registered_blueprint"
                child = _identity(call.args[0], module, imports)
                if child not in blueprints:
                    unresolved.append({
                        "source_file": record.relative, "line": call.lineno,
                        "reason": "unknown_registered_blueprint",
                        "child_identity": child,
                    })
                    continue
                prefix, valid, explicit = _literal_prefix(call)
                if not valid:
                    unresolved.append({
                        "source_file": record.relative, "line": call.lineno,
                        "reason": "dynamic_registration_prefix",
                        "child_identity": child,
                    })
                    continue
                if not explicit:
                    prefix = blueprints[child]["default_prefix"]
                registrations.append({
                    "blueprint_id": child, "parent_id": parent,
                    "host_kind": host_kind, "prefix": prefix,
                    "source_file": record.relative, "line": call.lineno,
                    "factory_scope": scope,
                })
    return registrations


def _active_prefixes(registrations: List[dict], unresolved: List[dict]) -> Dict[str, List[dict]]:
    """Only prefixes reachable from statically created Flask applications."""
    result: Dict[str, List[dict]] = {}
    by_parent: Dict[str, List[dict]] = {}
    for reg in registrations:
        if reg["parent_id"]:
            by_parent.setdefault(reg["parent_id"], []).append(reg)

    def visit(item: dict, outer: str, chain: Tuple[str, ...]) -> None:
        child = item["blueprint_id"]
        if child in chain:
            unresolved.append({
                "source_file": item["source_file"], "line": item["line"],
                "reason": "cyclic_blueprint_registration", "blueprint_id": child,
            })
            return
        prefix = outer.rstrip("/") + item["prefix"]
        observation = {
            "blueprint_id": child, "url_prefix": prefix,
            "registration_file": item["source_file"],
            "registration_line": item["line"],
            "registration_chain": list(chain + (child,)),
        }
        entries = result.setdefault(child, [])
        if observation not in entries:
            entries.append(observation)
        for nested in by_parent.get(child, []):
            visit(nested, prefix, chain + (child,))

    for reg in registrations:
        if not reg["parent_id"]:
            visit(reg, "", ())
    return result


def enrich_flask_blueprint_routes(graph: SemanticGraph, root: Path) -> None:
    source = get_python_source_session(root)
    unresolved: List[dict] = []
    blueprints = _collect_declarations(source, unresolved)
    regs = _registrations(source, blueprints, unresolved)
    active = _active_prefixes(regs, unresolved)

    # Existing function nodes come from language extraction. Only the exact
    # file+function interval owns a route declaration, never a same-name search.
    callable_index = _CallableLineIndex(graph)
    declared_routes: List[dict] = []
    emitted: List[dict] = []
    for record in source.records():
        if record.tree is None:
            continue
        module = _module_name(record.relative)
        imports = _imports(record.tree.body, module,
                           record.relative.endswith("/__init__.py"))
        definitions = source.ast_index(record.path).functions
        owners = callable_index.resolve_many(
            record.relative, [getattr(item, "lineno", 1) for item in definitions],
        )
        global_flask_instances = {
            name for name, _ in _assignments(
                record.tree.body, module, imports, "flask.Flask",
            )
        }
        for definition in definitions:
            owner = owners.get(getattr(definition, "lineno", 1))
            if owner is None or not isinstance(
                definition, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            for decorator in definition.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                operation = decorator.func.attr
                if operation not in set(ROUTE_METHODS) | {"route"}:
                    continue
                fragment, methods = _route_args(decorator, operation)
                if fragment is None or methods is None:
                    unresolved.append({
                        "source_file": record.relative, "line": decorator.lineno,
                        "source_node_id": owner.id,
                        "reason": "dynamic_or_invalid_route_or_methods",
                    })
                    continue
                host = _expr_name(decorator.func.value)
                blueprint_id = _identity(decorator.func.value, module, imports)
                declaration = {
                    "source_node_id": owner.id,
                    "source_file": record.relative, "line": decorator.lineno,
                    "route_fragment": fragment, "methods": methods,
                    "blueprint_id": blueprint_id if blueprint_id in blueprints else None,
                }
                declared_routes.append(declaration)
                if owner.kind == NodeKind.FUNCTION:
                    mark_role(
                        owner, "flask", NodeKind.HANDLER, "request_handler",
                        "Flask route decorator with statically parsed route",
                    )
                if blueprint_id in blueprints:
                    registrations = active.get(blueprint_id, [])
                    if not registrations:
                        unresolved.append(dict(
                            declaration, reason="blueprint_not_statically_registered",
                        ))
                    for reg in registrations:
                        full = _join(reg["url_prefix"], fragment)
                        add_contract(
                            owner, "http_server", full, 0.98,
                            methods=methods, framework="flask",
                            derivation="flask.blueprint.registered_route",
                            evidence_kind="static",
                            source_file=record.relative,
                            source_line=decorator.lineno,
                            route_fragment=fragment, blueprint_id=blueprint_id,
                            blueprint_declaration_file=blueprints[blueprint_id]["declaration_file"],
                            blueprint_declaration_line=blueprints[blueprint_id]["declaration_line"],
                            registration_file=reg["registration_file"],
                            registration_line=reg["registration_line"],
                            registration_chain=reg["registration_chain"],
                            url_prefix=reg["url_prefix"],
                        )
                        emitted.append(dict(
                            declaration, target=full,
                            registration_file=reg["registration_file"],
                            registration_line=reg["registration_line"],
                        ))
                elif host in global_flask_instances:
                    add_contract(
                        owner, "http_server", fragment, 0.98,
                        methods=methods, framework="flask",
                        derivation="flask.application.direct_route",
                        evidence_kind="static", source_file=record.relative,
                        source_line=decorator.lineno,
                    )
                    emitted.append(dict(declaration, target=fragment))
                else:
                    unresolved.append(dict(
                        declaration, reason="unknown_route_decorator_host",
                    ))

    graph.metadata["flask_blueprint_composition"] = {
        "version": "1.0.0", "blueprints": [
            blueprints[key] for key in sorted(blueprints)
        ], "registrations": regs,
        "active_prefixes": active, "declared_routes": declared_routes,
        "emitted_routes": emitted, "unresolved": unresolved,
    }
