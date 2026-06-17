"""Component-level source metrics for Python AST nodes."""

import ast
from typing import Any, Dict


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

_RELATION_NAMES = {
    "ForeignKey",
    "OneToOneField",
    "ManyToManyField",
    "relationship",
}


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
        name = _call_name(node.func)
        if name in _RELATION_NAMES:
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
    """Return raw, explainable metrics for exactly one AST component."""
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    visitor = _ScopedMetricVisitor(node)
    visitor.visit(node)

    cyclomatic = 1 + visitor.branches + visitor.exception_handlers
    loc = max(1, end - start + 1)
    return {
        "loc": loc,
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
    """Derive bounded physics notation values from component metrics."""
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

    energy = 0.35 + min(calls, 20.0) * 0.04 + min(cyclomatic, 15.0) * 0.025
    coupling = 0.25 + min(calls + relationships, 15.0) * 0.04
    charge = 1.0 + min(relationships, 5.0) * 0.05 if node_type == "PARTICLE" else 1.0

    return {
        "mass": round(min(2.0, max(0.1, mass)), 2),
        "energy": round(min(1.5, max(0.1, energy)), 2),
        "coupling": round(min(1.0, max(0.1, coupling)), 2),
        "charge": round(min(1.25, charge), 2),
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
