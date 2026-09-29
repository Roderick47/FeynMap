"""P1.2: source-grounded Django class-based-view model/template semantics.

Only recognize direct known Django generic CBV bases. Resolve model names
through imports and exact qualified graph identities, never a repository-wide
short-name guess. Default template names require a unique existing HTML file;
an explicitly declared name is recorded even if its target cannot be proven.
No Django code is imported or executed.
"""
from __future__ import annotations

import ast
import hashlib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from feynmap.core import (
    EdgeKind, Evidence, EvidenceKind, NodeKind,
    SemanticEdge, SemanticGraph, SemanticNode, SourceLocation,
)
from feynmap.integration import add_contract

from ..python_source import get_python_source_session
from ._python import mark_role


# Canonical Django generic classes only. The import must establish the
# django.views.generic namespace (or its actual submodule); a local class
# coincidentally called ListView/DetailView is not enough.
_GENERIC_MODULES = {
    "ListView": {"django.views.generic", "django.views.generic.list"},
    "DetailView": {"django.views.generic", "django.views.generic.detail"},
    "CreateView": {"django.views.generic", "django.views.generic.edit"},
    "UpdateView": {"django.views.generic", "django.views.generic.edit"},
    "DeleteView": {"django.views.generic", "django.views.generic.edit"},
    "TemplateView": {"django.views.generic", "django.views.generic.base"},
}
_DEFAULT_SUFFIXES = {
    "ListView": "_list",
    "DetailView": "_detail",
    "CreateView": "_form",
    "UpdateView": "_form",
    "DeleteView": "_confirm_delete",
}
_QUERYSET_METHODS = frozenset({
    "all", "filter", "exclude", "order_by", "distinct", "none", "using",
    "select_related", "prefetch_related", "annotate", "values", "values_list",
    "only", "defer", "reverse", "select_for_update",
})
_SKIPPED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", "dist", "build", ".feynmap",
})


def _dotted(expr: ast.AST) -> Optional[str]:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        prefix = _dotted(expr.value)
        return (prefix + "." + expr.attr) if prefix else None
    return None


def _module_name(relative: str) -> str:
    parts = list(PurePosixPath(relative).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_map(tree: ast.Module, relative: str) -> Dict[str, Optional[str]]:
    """Import-local name -> fully qualified symbol; conflicts remain unknown."""

    module = _module_name(relative)
    is_package = PurePosixPath(relative).name == "__init__.py"
    package = module.split(".") if is_package else module.split(".")[:-1]
    bound: Dict[str, Optional[str]] = {}

    def set_name(name: str, qualified: str) -> None:
        if name in bound and bound[name] != qualified:
            bound[name] = None
        else:
            bound[name] = qualified

    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                set_name(local, target)
        elif isinstance(statement, ast.ImportFrom):
            if statement.level:
                keep = len(package) - statement.level + 1
                if keep < 0:
                    continue
                parent = package[:keep]
                prefix = ".".join(parent + ([statement.module] if statement.module else []))
            else:
                prefix = statement.module or ""
            for alias in statement.names:
                if alias.name == "*":
                    continue
                qualified = (prefix + "." + alias.name) if prefix else alias.name
                set_name(alias.asname or alias.name, qualified)

    # A module-level local assignment can shadow an imported name. Do not
    # pretend its reference still points to the imported model or CBV base.
    for statement in tree.body:
        assigned: List[ast.Name] = []
        if isinstance(statement, ast.Assign):
            assigned = [
                item for target in statement.targets
                for item in ast.walk(target) if isinstance(item, ast.Name)
            ]
        elif isinstance(statement, ast.AnnAssign):
            assigned = [
                item for item in ast.walk(statement.target)
                if isinstance(item, ast.Name)
            ]
        for item in assigned:
            if item.id in bound:
                bound[item.id] = None
    return bound


def _expand(expression: str, imports: Mapping[str, Optional[str]], module: str) -> Optional[str]:
    head, dot, tail = expression.partition(".")
    if head in imports:
        imported = imports[head]
        return (imported + (("." + tail) if dot else "")) if imported else None
    # No import means the only defensible interpretation is a local symbol.
    return (module + "." + expression) if module else expression


def _generic_kind(definition: ast.ClassDef, imports: Mapping[str, Optional[str]]) -> Optional[str]:
    for base in definition.bases:
        raw = _dotted(base)
        if not raw:
            continue
        # A Django generic must be proven by import, not by suffix alone.
        head = raw.split(".", 1)[0]
        if head not in imports or not imports[head]:
            continue
        resolved = _expand(raw, imports, "")
        if not resolved or "." not in resolved:
            continue
        module, name = resolved.rsplit(".", 1)
        if module in _GENERIC_MODULES.get(name, set()):
            return name
    return None


def _attributes(definition: ast.ClassDef) -> Dict[str, ast.AST]:
    """Last direct class-body assignment wins, without walking nested scopes."""

    result: Dict[str, ast.AST] = {}
    for statement in definition.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.value is not None:
                result[statement.target.id] = statement.value
    return result


def _queryset_model(expression: ast.AST) -> Optional[str]:
    """Recognize Book.objects[.known_queryset_method(...)] without executing it."""

    value = expression
    while isinstance(value, ast.Call):
        func = value.func
        if not isinstance(func, ast.Attribute) or func.attr not in _QUERYSET_METHODS:
            return None
        value = func.value
    if isinstance(value, ast.Attribute) and value.attr == "objects":
        return _dotted(value.value)
    return None


def _model_node(
    expression: str,
    imports: Mapping[str, Optional[str]],
    module: str,
    models_by_qualified: Mapping[str, Sequence[SemanticNode]],
) -> Optional[SemanticNode]:
    qualified = _expand(expression, imports, module)
    if not qualified:
        return None
    matches = models_by_qualified.get(qualified, ())
    return matches[0] if len(matches) == 1 else None


def _logical_templates(root: Path) -> Dict[str, Tuple[str, ...]]:
    """Map Django logical template names to all their physical repo paths."""

    values: Dict[str, Set[str]] = {}
    for file in root.rglob("*.html"):
        if not file.is_file():
            continue
        relative = file.relative_to(root).as_posix()
        parts = PurePosixPath(relative).parts
        if any(part in _SKIPPED_DIRS for part in parts):
            continue
        for index, part in enumerate(parts[:-1]):
            if part == "templates" and index + 1 < len(parts):
                logical = "/".join(parts[index + 1:])
                values.setdefault(logical, set()).add(relative)
                break
    return {key: tuple(sorted(paths)) for key, paths in values.items()}


def _template_label(expression: ast.AST) -> Optional[str]:
    if not isinstance(expression, ast.Constant) or not isinstance(expression.value, str):
        return None
    label = expression.value.replace("\\", "/").strip().lstrip("/")
    parts = PurePosixPath(label).parts
    if not label.endswith(".html") or not parts or any(
        part in {".", ".."} for part in parts
    ):
        return None
    if any(symbol in label for symbol in ("{", "}", "%", "*")):
        return None
    return label


def _model_app(model: SemanticNode) -> Optional[str]:
    """Derive an app label only from an in-repo models.py/models/ file."""

    if not model.location:
        return None
    parts = PurePosixPath(model.location.path).parts
    if len(parts) >= 2 and parts[-1] == "models.py":
        return parts[-2]
    if "models" in parts[:-1]:
        index = parts.index("models")
        if index >= 1:
            return parts[index - 1]
    return None


def _add_model_edge(
    graph: SemanticGraph,
    seen: Set[Tuple[str, str, str]],
    view: SemanticNode,
    model: SemanticNode,
    binding: str,
    location: SourceLocation,
) -> bool:
    key = (view.id, model.id, EdgeKind.USES_DATA.value)
    if key in seen:
        return False
    raw = "%s|%s|django_cbv_model" % (view.id, model.id)
    confidence = 0.99 if binding == "model" else 0.94
    edge = SemanticEdge(
        id="edge:django-cbv:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
        source=view.id,
        target=model.id,
        kind=EdgeKind.USES_DATA,
        confidence=confidence,
        evidence=[Evidence(
            EvidenceKind.STATIC,
            "django.cbv.%s_assignment" % binding,
            "Django CBV %s references in-repo model %s" % (binding, model.qualified_name),
            location,
            confidence,
        )],
        attributes={
            "framework": {"name": "django", "relationship": "cbv_uses_model"},
            "django_cbv": {"binding": binding, "resolved_model": model.qualified_name},
        },
    )
    graph.add_edge(edge)
    seen.add(key)
    return True


def enrich_django_cbvs(graph: SemanticGraph, root: Path) -> None:
    """Attach safe per-class semantic facts before the language graph merge."""

    root = root.resolve()
    session = get_python_source_session(root)
    by_identity: Dict[Tuple[str, str, int], List[SemanticNode]] = {}
    models_by_qualified: Dict[str, List[SemanticNode]] = {}
    for node in graph.nodes:
        if node.language != "python":
            continue
        if node.kind == NodeKind.DATA_MODEL and node.qualified_name:
            models_by_qualified.setdefault(node.qualified_name, []).append(node)
        if (
            node.kind in {NodeKind.HANDLER, NodeKind.CLASS} and node.location
            and node.location.line is not None
        ):
            key = (node.location.path, node.name, node.location.line)
            by_identity.setdefault(key, []).append(node)

    template_paths = _logical_templates(root)
    edge_keys = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
    stats: Counter = Counter()

    for record in session.records():
        if record.tree is None:
            continue
        imports = _import_map(record.tree, record.relative)
        module = _module_name(record.relative)
        # Direct module classes only. Nested classes should not accidentally
        # match a same-name handler by line-number coincidence.
        classes = [node for node in record.tree.body if isinstance(node, ast.ClassDef)]
        for definition in classes:
            generic = _generic_kind(definition, imports)
            if generic is None:
                continue
            candidates = by_identity.get(
                (record.relative, definition.name, definition.lineno), ()
            )
            if len(candidates) != 1:
                stats["ambiguous_owner"] += 1
                continue
            view = candidates[0]
            # The older generic adapter recognizes suffixes such as ListView
            # but may not recognize "ListView as CoreList". The resolved import
            # above provides firmer evidence than the suffix heuristic.
            if view.kind == NodeKind.CLASS:
                mark_role(
                    view, "django", NodeKind.HANDLER, "request_handler",
                    "Django generic CBV base resolved through its imported identity",
                )
            stats["recognized_cbvs"] += 1
            attrs = _attributes(definition)
            notes: Dict[str, object] = {"generic_base": generic, "bindings": {}, "unresolved": []}
            resolved_bindings: Dict[str, SemanticNode] = {}

            for binding in ("model", "queryset"):
                value = attrs.get(binding)
                if value is None:
                    continue
                expression = _dotted(value) if binding == "model" else _queryset_model(value)
                if not expression:
                    notes["unresolved"].append("%s:dynamic_expression" % binding)
                    stats["unresolved_binding"] += 1
                    continue
                model = _model_node(
                    expression, imports, module, models_by_qualified
                )
                if model is None:
                    notes["unresolved"].append("%s:unresolved_or_ambiguous:%s" % (binding, expression))
                    stats["unresolved_binding"] += 1
                    continue
                resolved_bindings[binding] = model
                notes["bindings"][binding] = model.qualified_name
                if _add_model_edge(
                    graph, edge_keys, view, model, binding,
                    SourceLocation(record.relative, getattr(value, "lineno", definition.lineno)),
                ):
                    stats["model_edges_added"] += 1

            template_expr = attrs.get("template_name")
            if template_expr is not None:
                label = _template_label(template_expr)
                # A declaration is a source fact, but a RENDERS edge needs a
                # unique in-repository template; absent/ambiguous is unknown.
                notes["declared_template_name"] = label
                paths = template_paths.get(label or "", ())
                if label and len(paths) == 1:
                    add_contract(
                        view, "template_render", label, 0.98,
                        framework="django", derivation="django.cbv.explicit_template",
                        evidence_kind=EvidenceKind.STATIC.value,
                        line=getattr(template_expr, "lineno", definition.lineno),
                        resolved_template_path=paths[0],
                    )
                    stats["explicit_template_contracts"] += 1
                    notes["template_evidence"] = "explicit"
                else:
                    notes["unresolved"].append("template_name:missing_dynamic_or_ambiguous")
                    stats["unresolved_template"] += 1
            elif generic in _DEFAULT_SUFFIXES:
                # A custom implementation may choose a different template.
                # Do not infer a default when it overrides get_template_names.
                if any(
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "get_template_names"
                    for item in definition.body
                ):
                    notes["unresolved"].append("template:custom_get_template_names")
                    stats["unresolved_template"] += 1
                elif attrs.get("queryset") is not None and "queryset" not in resolved_bindings:
                    notes["unresolved"].append("template:queryset_model_unknown")
                    stats["unresolved_template"] += 1
                else:
                    model = resolved_bindings.get("queryset") or resolved_bindings.get("model")
                    if model is None or len({item.id for item in resolved_bindings.values()}) > 1:
                        notes["unresolved"].append("template:missing_or_conflicting_model")
                        stats["unresolved_template"] += 1
                    else:
                        app = _model_app(model)
                        suffix_expr = attrs.get("template_name_suffix")
                        suffix = _DEFAULT_SUFFIXES[generic]
                        if suffix_expr is not None:
                            if (
                                isinstance(suffix_expr, ast.Constant)
                                and isinstance(suffix_expr.value, str)
                                and suffix_expr.value
                            ):
                                suffix = suffix_expr.value
                            else:
                                suffix = ""
                        logical = (
                            "%s/%s%s.html" % (app, model.name.lower(), suffix)
                            if app and suffix else None
                        )
                        paths = template_paths.get(logical or "", ())
                        if logical and len(paths) == 1:
                            # A framework convention is intentionally inferred,
                            # not as strong as an explicit source declaration.
                            add_contract(
                                view, "template_render", logical, 0.70,
                                framework="django", derivation="django.cbv.default_template",
                                evidence_kind=EvidenceKind.FRAMEWORK.value,
                                inferred_from=model.qualified_name,
                                resolved_template_path=paths[0],
                            )
                            stats["default_template_contracts"] += 1
                            notes["template_evidence"] = "framework_convention"
                            notes["inferred_template_name"] = logical
                        else:
                            notes["unresolved"].append("template:missing_or_ambiguous_default")
                            stats["unresolved_template"] += 1
            view.attributes["django_cbv"] = notes

    graph.metadata["django_cbv"] = dict(sorted(stats.items()))
