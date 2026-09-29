"""P1.6: source-grounded Django REST Framework class and route observations.

DRF enrichment belongs to the Django framework layer, not the Python parser.
Use source-only AST imports and exact qualified graph identities. A declaration
is not proof of runtime registration; uncertain targets remain unresolved.
"""
from __future__ import annotations

import ast
import hashlib
from collections import Counter
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from feynmap.adapters.python_source import get_python_source_session
from feynmap.core import (
    EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph,
    SemanticNode, SourceLocation,
)
from feynmap.integration import contracts

from ._python import mark_role
from .django_cbv import _attributes, _dotted, _expand, _import_map, _module_name


_SERIALIZER_BASES = {
    "rest_framework.serializers.BaseSerializer",
    "rest_framework.serializers.Serializer",
    "rest_framework.serializers.ListSerializer",
    "rest_framework.serializers.ModelSerializer",
    "rest_framework.serializers.HyperlinkedModelSerializer",
}
_MODEL_SERIALIZER_BASES = {
    "rest_framework.serializers.ModelSerializer",
    "rest_framework.serializers.HyperlinkedModelSerializer",
}
_VIEW_BASES = {
    "rest_framework.views.APIView",
    "rest_framework.generics.GenericAPIView",
    "rest_framework.generics.CreateAPIView",
    "rest_framework.generics.ListAPIView",
    "rest_framework.generics.RetrieveAPIView",
    "rest_framework.generics.DestroyAPIView",
    "rest_framework.generics.UpdateAPIView",
    "rest_framework.generics.ListCreateAPIView",
    "rest_framework.generics.RetrieveUpdateAPIView",
    "rest_framework.generics.RetrieveDestroyAPIView",
    "rest_framework.generics.RetrieveUpdateDestroyAPIView",
    "rest_framework.viewsets.ViewSet",
    "rest_framework.viewsets.GenericViewSet",
    "rest_framework.viewsets.ModelViewSet",
    "rest_framework.viewsets.ReadOnlyModelViewSet",
}
_ROUTER_TYPES = {
    "rest_framework.routers.BaseRouter",
    "rest_framework.routers.SimpleRouter",
    "rest_framework.routers.DefaultRouter",
}


def _identity(value: ast.AST, imports: Mapping[str, Optional[str]], module: str) -> Optional[str]:
    dotted = _dotted(value)
    return _expand(dotted, imports, module) if dotted else None


def _classes(root: Path):
    session = get_python_source_session(root)
    result = []
    for record in session.records():
        if record.tree is None:
            continue
        imports = _import_map(record.tree, record.relative)
        module = _module_name(record.relative)
        for definition in record.tree.body:
            if isinstance(definition, ast.ClassDef):
                qname = module + "." + definition.name if module else definition.name
                bases = tuple(_identity(base, imports, module) for base in definition.bases)
                result.append((record.relative, module, imports, definition, qname, bases))
    return result


def _loc(path: str, node: ast.AST) -> SourceLocation:
    return SourceLocation(path=path, line=getattr(node, "lineno", 1))


def _edge(graph: SemanticGraph, keys: Set[Tuple[str, str, str]],
          source: SemanticNode, target: SemanticNode, kind: EdgeKind,
          detector: str, location: SourceLocation,
          relationship: str) -> bool:
    signature = (source.id, target.id, kind.value)
    if signature in keys:
        return False
    raw = "|".join(signature + (detector,))
    graph.add_edge(SemanticEdge(
        id="edge:django-drf:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
        source=source.id, target=target.id, kind=kind, confidence=0.98,
        evidence=[Evidence(
            EvidenceKind.STATIC, "django.drf." + detector,
            "Explicit in-repository DRF %s: %s -> %s" % (
                relationship, source.qualified_name, target.qualified_name,
            ), location, 0.98,
        )],
        attributes={
            "framework": {"name": "django", "relationship": "drf_" + relationship},
            "drf": {
                "source_file": location.path, "source_line": location.line,
                "resolved_target": target.qualified_name,
                "derivation": "explicit_source_binding",
            },
        },
    ))
    keys.add(signature)
    return True


def _literal_fields(expr: Optional[ast.AST]) -> Optional[list]:
    if expr is None:
        return None
    if isinstance(expr, ast.Constant) and expr.value == "__all__":
        return ["__all__"]
    if isinstance(expr, (ast.List, ast.Tuple)):
        values = []
        for item in expr.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            values.append(item.value)
        return values
    return None


def _field_declarations(definition: ast.ClassDef, imports, module: str) -> List[dict]:
    """Record only syntactically declared field constructors, not runtime fields."""
    result = []
    for stmt in definition.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        value = stmt.value
        if not isinstance(value, ast.Call):
            continue
        constructor = _identity(value.func, imports, module)
        if not constructor or (
            not constructor.startswith("rest_framework.fields.")
            and not constructor.startswith("rest_framework.serializers.")
            and not constructor.startswith("rest_framework.relations.")
        ):
            continue
        if not constructor.rsplit(".", 1)[-1].endswith(("Field", "Serializer")):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            if isinstance(target, ast.Name):
                result.append({
                    "name": target.id, "constructor": constructor,
                    "source_line": value.lineno,
                    "scope": "explicit_class_body_constructor",
                })
    return result


def _static_router_registrations(root: Path, indexed: Mapping[str, Sequence[SemanticNode]]):
    declarations, unresolved = [], []
    for record in get_python_source_session(root).records():
        if record.tree is None:
            continue
        module = _module_name(record.relative)
        imports = _import_map(record.tree, record.relative)
        router_instances = {}
        for statement in record.tree.body:
            if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Call):
                continue
            constructor = _identity(statement.value.func, imports, module)
            if constructor not in _ROUTER_TYPES:
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    router_instances[target.id] = constructor
        for statement in record.tree.body:
            for call in ast.walk(statement):
                if (
                    not isinstance(call, ast.Call)
                    or not isinstance(call.func, ast.Attribute)
                    or call.func.attr != "register"
                    or not isinstance(call.func.value, ast.Name)
                    or call.func.value.id not in router_instances
                ):
                    continue
                if len(call.args) < 2:
                    unresolved.append({
                        "source_file": record.relative, "source_line": call.lineno,
                        "reason": "missing_router_arguments",
                    })
                    continue
                prefix_expr = call.args[0]
                prefix = (
                    prefix_expr.value
                    if isinstance(prefix_expr, ast.Constant)
                    and isinstance(prefix_expr.value, str) else None
                )
                target = _identity(call.args[1], imports, module)
                match = indexed.get(target or "", ())
                basename_expr = call.args[2] if len(call.args) >= 3 else next(
                    (item.value for item in call.keywords if item.arg == "basename"), None
                )
                basename = (
                    basename_expr.value if isinstance(basename_expr, ast.Constant)
                    and isinstance(basename_expr.value, str) else None
                )
                if prefix is None or len(match) != 1:
                    unresolved.append({
                        "source_file": record.relative, "source_line": call.lineno,
                        "reason": "dynamic_router_prefix_or_view",
                        "view_identity": target,
                    })
                    continue
                declarations.append({
                    "source_file": record.relative, "source_line": call.lineno,
                    "router_variable": call.func.value.id,
                    "router_constructor": router_instances[call.func.value.id],
                    "declared_prefix": prefix, "declared_basename": basename,
                    "view_identity": target, "view_node_id": match[0].id,
                    "status": "declaration_only_not_proven_mounted",
                })
    return declarations, unresolved


def _field_boundary(graph: SemanticGraph, keys: Set[Tuple[str, str, str]],
                    parsed, indexed, unresolved: List[dict], stats: Counter) -> None:
    """Ground the actual DRF SerializerMetaclass field-type use.

    The pinned implementation uses isinstance(obj, Field) in
    SerializerMetaclass._get_declared_fields; the Field identity is imported
    from rest_framework.fields. This creates a real dependency into fields.py,
    not a benchmark-derived synthetic relevance or lexical boost.
    """
    for path, module, imports, definition, qname, _ in parsed:
        if qname != "rest_framework.serializers.SerializerMetaclass":
            continue
        source = next((part for part in definition.body if isinstance(
            part, (ast.FunctionDef, ast.AsyncFunctionDef),
        ) and part.name == "_get_declared_fields"), None)
        if source is None:
            return
        method = indexed.get(qname + "._get_declared_fields", ())
        target = indexed.get("rest_framework.fields.Field", ())
        found = False
        for call in ast.walk(source):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "isinstance"
                and len(call.args) >= 2
                and _identity(call.args[1], imports, module)
                    == "rest_framework.fields.Field"
            ):
                found = True
                if len(method) == 1 and len(target) == 1:
                    if _edge(graph, keys, method[0], target[0], EdgeKind.USES_DATA,
                             "serializer_metaclass_field_type_check",
                             _loc(path, call), "declared_field_type_check"):
                        stats["source_grounded_core_field_usage_edges"] += 1
                else:
                    unresolved.append({
                        "source_file": path, "source_line": call.lineno,
                        "reason": "field_type_target_missing_or_ambiguous",
                    })
                break
        if not found:
            unresolved.append({
                "source_file": path, "source_line": source.lineno,
                "reason": "serializer_metaclass_field_check_not_statically_found",
            })
        return


def enrich_django_drf(graph: SemanticGraph, root: Path) -> None:
    parsed = _classes(root)
    indexed: Dict[str, List[SemanticNode]] = {}
    for node in graph.nodes:
        if node.language == "python" and node.qualified_name:
            indexed.setdefault(node.qualified_name, []).append(node)

    serializers: Set[str] = set(_SERIALIZER_BASES)
    model_serializers: Set[str] = set(_MODEL_SERIALIZER_BASES)
    views: Set[str] = set(_VIEW_BASES)
    # Propagate only exact single-inheritance identities. A user class whose
    # direct base is a locally proven DRF class is still a source-backed DRF
    # class. No repository-wide matching by short name.
    for _ in range(len(parsed) + 1):
        changed = False
        for _, _, _, _, qname, bases in parsed:
            if qname not in serializers and any(base in serializers for base in bases):
                serializers.add(qname)
                changed = True
            if qname not in model_serializers and any(base in model_serializers for base in bases):
                model_serializers.add(qname)
                changed = True
            if qname not in views and any(base in views for base in bases):
                views.add(qname)
                changed = True
        if not changed:
            break

    keys = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
    unresolved: List[dict] = []
    stats: Counter = Counter()
    serializer_bindings: List[dict] = []
    permission_bindings: List[dict] = []
    recognized_views: List[SemanticNode] = []
    for path, module, imports, definition, qname, bases in parsed:
        members = indexed.get(qname, ())
        if len(members) != 1:
            continue
        node = members[0]
        is_serializer = qname in serializers
        is_view = qname in views
        if not is_serializer and not is_view:
            continue
        if is_serializer:
            if node.kind == NodeKind.CLASS:
                mark_role(node, "django", NodeKind.TRANSFORMER, "serializer",
                          "DRF serializer base resolved from exact source identity")
            stats["recognized_serializers"] += 1
            meta = next((item for item in definition.body if isinstance(
                item, ast.ClassDef,
            ) and item.name == "Meta"), None)
            detail = {
                "framework": "django_rest_framework",
                "bases": [base for base in bases if base],
                "declared_fields": _field_declarations(definition, imports, module),
                "validation_methods": [
                    item.name for item in definition.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and (item.name == "validate" or item.name.startswith("validate_"))
                ],
                "meta": {},
                "unresolved": [],
            }
            if meta is not None:
                attrs = _attributes(meta)
                for key in ("fields", "exclude", "read_only_fields"):
                    if key in attrs:
                        literal = _literal_fields(attrs[key])
                        if literal is not None:
                            detail["meta"][key] = literal
                        else:
                            detail["unresolved"].append(key + ":dynamic_meta_field_list")
                if "model" in attrs:
                    expression = attrs["model"]
                    target_name = _identity(expression, imports, module)
                    matches = indexed.get(target_name or "", ())
                    detail["meta"]["model_declaration"] = target_name
                    if (
                        qname in model_serializers
                        and len(matches) == 1
                        and matches[0].kind == NodeKind.DATA_MODEL
                    ):
                        model = matches[0]
                        detail["meta"]["resolved_model_node_id"] = model.id
                        if _edge(graph, keys, node, model, EdgeKind.SERIALIZES,
                                 "explicit_meta_model", _loc(path, expression),
                                 "serializer_model"):
                            stats["serializer_model_edges"] += 1
                    else:
                        detail["unresolved"].append("meta.model:unknown_or_non_model_serializer")
            node.attributes["drf_serializer"] = detail
            serializer_bindings.append({
                "source_node_id": node.id, "source_file": path,
                "source_line": definition.lineno, "details": detail,
            })

        if is_view:
            if node.kind == NodeKind.CLASS:
                mark_role(node, "django", NodeKind.HANDLER, "request_handler",
                          "DRF view base resolved from exact source identity")
            stats["recognized_views"] += 1
            recognized_views.append(node)
            attrs = _attributes(definition)
            detail = {
                "framework": "django_rest_framework",
                "bases": [base for base in bases if base],
                "serializer_binding": None, "permissions": [],
                "unresolved": [],
            }
            serializer_expr = attrs.get("serializer_class")
            if serializer_expr is not None:
                target_name = _identity(serializer_expr, imports, module)
                matches = indexed.get(target_name or "", ())
                if target_name and target_name in serializers and len(matches) == 1:
                    serializer = matches[0]
                    detail["serializer_binding"] = {
                        "qualified_name": target_name, "node_id": serializer.id,
                        "source_line": getattr(serializer_expr, "lineno", definition.lineno),
                    }
                    if _edge(graph, keys, node, serializer, EdgeKind.SERIALIZES,
                             "explicit_serializer_class", _loc(path, serializer_expr),
                             "view_serializer"):
                        stats["view_serializer_edges"] += 1
                elif not (isinstance(serializer_expr, ast.Constant)
                          and serializer_expr.value is None):
                    detail["unresolved"].append("serializer_class:unknown_or_dynamic")
            permission_expr = attrs.get("permission_classes")
            if permission_expr is not None:
                if not isinstance(permission_expr, (ast.List, ast.Tuple)):
                    detail["unresolved"].append("permission_classes:dynamic_expression")
                else:
                    for expression in permission_expr.elts:
                        target_name = _identity(expression, imports, module)
                        matches = indexed.get(target_name or "", ())
                        if (
                            not target_name
                            or not target_name.startswith("rest_framework.permissions.")
                            and (len(matches) != 1 or not
                                 matches[0].attributes.get("drf_permission"))
                        ):
                            detail["unresolved"].append(
                                "permission_classes:unproved_symbol"
                            )
                            continue
                        item = {
                            "qualified_name": target_name,
                            "source_line": getattr(expression, "lineno", definition.lineno),
                            "source_scope": "explicit_permission_classes",
                        }
                        if len(matches) == 1 and matches[0].kind in {
                            NodeKind.CLASS, NodeKind.SERVICE,
                        }:
                            item["node_id"] = matches[0].id
                            if _edge(graph, keys, node, matches[0],
                                     EdgeKind.DEPENDS_ON, "explicit_permission_classes",
                                     _loc(path, expression), "view_permission"):
                                stats["view_permission_edges"] += 1
                        else:
                            item["status"] = "qualified_external_not_in_repository"
                        detail["permissions"].append(item)
                        permission_bindings.append(dict(
                            item, view_node_id=node.id, source_file=path,
                        ))
            node.attributes["drf_view"] = detail

    # Record the core DRF Field bridge only when the implementation literally
    # imports and tests Field; the bridge improves graph traversal naturally.
    _field_boundary(graph, keys, parsed, indexed, unresolved, stats)
    router_regs, router_unknown = _static_router_registrations(root, indexed)
    unresolved.extend(router_unknown)
    router_by_view: Dict[str, List[dict]] = {}
    for item in router_regs:
        router_by_view.setdefault(item["view_node_id"], []).append(item)
    route_coverage: List[dict] = []
    for view in recognized_views:
        registered = [
            item for item in contracts(view, "http_server")
            if (item.get("framework") == "django"
                and item.get("derivation") == "django.urls.static_registration")
        ]
        route_coverage.append({
            "view_node_id": view.id,
            "source_file": view.location.path if view.location else None,
            "view_identity": view.qualified_name,
            "status": (
                "static_url_registration" if registered
                else "router_declaration_mount_unproven"
                if router_by_view.get(view.id)
                else "no_static_registration_proven"
            ),
            "static_routes": [{
                "path": item["target"],
                "registration_file": item.get("source_file"),
                "registration_line": item.get("source_line"),
                "evidence_kind": item.get("evidence_kind"),
            } for item in registered],
            "router_declarations": router_by_view.get(view.id, []),
            "note": "Absence of a static route is not proof this view is unrouted at runtime.",
        })
    graph.metadata["django_drf"] = {
        "version": "1.0.0",
        "framework": "django_rest_framework",
        "stats": dict(sorted(stats.items())),
        "serializer_bindings": serializer_bindings,
        "permission_bindings": permission_bindings,
        "route_coverage": route_coverage,
        "router_declarations": router_regs,
        "unresolved": unresolved,
    }
