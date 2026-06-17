"""Component-level source metrics and parser integration."""

import ast
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Type


_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
    ast.Assert,
    ast.comprehension,
)
_RELATION_NAMES = {"ForeignKey", "OneToOneField", "ManyToManyField", "relationship"}


class _ScopedMetricVisitor(ast.NodeVisitor):
    """Measure one component without descending into nested components."""

    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.calls = 0
        self.branches = 0
        self.assignments = 0
        self.returns = 0
        self.raises = 0
        self.exception_handlers = 0
        self.fields = 0
        self.relationships = 0

    def visit_Call(self, node: ast.Call) -> None:
        self.calls += 1
        if _call_name(node.func) in _RELATION_NAMES:
            self.relationships += 1
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, _BRANCH_NODES):
            self.branches += 1
        if isinstance(node, ast.ExceptHandler):
            self.exception_handlers += 1
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            self.assignments += 1
        if isinstance(node, ast.Return):
            self.returns += 1
        if isinstance(node, ast.Raise):
            self.raises += 1
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is not self.root:
            return
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self.fields += 1
            self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        if node is self.root:
            self.visit(node.body)


def calculate_component_metrics(node: ast.AST) -> Dict[str, Any]:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    visitor = _ScopedMetricVisitor(node)
    visitor.visit(node)
    cyclomatic = 1 + visitor.branches + visitor.exception_handlers
    return {
        "loc": max(1, end - start + 1),
        "cyclomatic_complexity": cyclomatic,
        "branch_count": visitor.branches,
        "call_count": visitor.calls,
        "assignment_count": visitor.assignments,
        "return_count": visitor.returns,
        "raise_count": visitor.raises,
        "exception_handler_count": visitor.exception_handlers,
        "field_count": visitor.fields,
        "relationship_count": visitor.relationships,
    }


def derive_physics_metrics(metrics: Dict[str, Any], node_type: str) -> Dict[str, float]:
    loc = float(metrics.get("loc", 1))
    cyclomatic = float(metrics.get("cyclomatic_complexity", 1))
    calls = float(metrics.get("call_count", 0))
    fields = float(metrics.get("field_count", 0))
    relationships = float(metrics.get("relationship_count", 0))

    mass = 0.2 + min(loc, 200.0) / 100.0 + (cyclomatic - 1.0) * 0.12 + calls * 0.03
    if node_type == "PARTICLE":
        mass += fields * 0.08 + relationships * 0.16
    elif node_type == "TRANSFORM":
        mass += fields * 0.05

    return {
        "mass": round(min(2.0, max(0.1, mass)), 2),
        "energy": round(min(1.5, 0.35 + min(calls, 20.0) * 0.04 + min(cyclomatic, 15.0) * 0.025), 2),
        "coupling": round(min(1.0, 0.25 + min(calls + relationships, 15.0) * 0.04), 2),
        "charge": round(min(1.25, 1.0 + relationships * 0.05), 2) if node_type == "PARTICLE" else 1.0,
    }


def install_component_metric_calculator(extractor_class: Type[Any]) -> None:
    """Replace legacy file-wide metadata calculation once per process."""
    if getattr(extractor_class, "_component_metrics_installed", False):
        return

    legacy_calculator = extractor_class._calculate_metadata

    def calculate_metadata(
        self: Any, node_name: str, node_type: str, file_name: str, **kwargs: Any
    ) -> Dict[str, Any]:
        node = _find_component(file_name, node_name, kwargs.get("line_start"), kwargs.get("line_end"))
        if node is None:
            metadata = legacy_calculator(self, node_name, node_type, file_name, **kwargs)
            metadata.setdefault("metrics", {})
            metadata["metric_scope"] = "fallback"
            return metadata

        metrics = calculate_component_metrics(node)
        physics = derive_physics_metrics(metrics, node_type)
        metadata = {
            "mass": physics["mass"],
            "charge": physics["charge"],
            "spin": 0.5,
            "energy": physics["energy"],
            "coupling": physics["coupling"],
            "lifetime": 1.0,
            "file": file_name,
            "lines": metrics["loc"],
            "line_start": kwargs.get("line_start"),
            "line_end": kwargs.get("line_end"),
            "metrics": metrics,
            "metric_scope": "component",
        }
        if node_type == "FRONTEND":
            metadata["mass"] = self._calculate_template_complexity(node_name, file_name)
            metadata["metric_scope"] = "template_file"
        elif node_type == "AJAX":
            metadata["energy"] = 1.0
            metadata["coupling"] = 0.7
        return metadata

    extractor_class._calculate_metadata = calculate_metadata
    extractor_class._component_metrics_installed = True


@lru_cache(maxsize=512)
def _parse_file(file_name: str) -> Optional[ast.AST]:
    try:
        return ast.parse(Path(file_name).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None


def _find_component(
    file_name: str, name: str, line_start: Optional[int], line_end: Optional[int]
) -> Optional[ast.AST]:
    tree = _parse_file(str(Path(file_name).resolve()))
    if tree is None:
        return None
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and getattr(node, "name", None) == name
    ]
    if line_start is not None:
        exact = [node for node in candidates if getattr(node, "lineno", None) == line_start]
        if len(exact) == 1:
            return exact[0]
    if line_start is not None and line_end is not None:
        spanning = [
            node
            for node in candidates
            if getattr(node, "lineno", 0) <= line_start
            and getattr(node, "end_lineno", 0) >= line_end
        ]
        if len(spanning) == 1:
            return spanning[0]
    return candidates[0] if len(candidates) == 1 else None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
