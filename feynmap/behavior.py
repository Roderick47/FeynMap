"""Source-backed behavioral observations for task-conditioned context.

P2.4 deliberately keeps behavioral facts outside the canonical semantic graph.
The graph remains the stable language-neutral truth/index layer; this module
reads the selected source witnesses and derives a bounded observation envelope
with exact provenance.  Observations never upgrade graph confidence and are
safe to discard/recompute for another task.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .core import EvidenceKind, SemanticGraph, SemanticNode, SourceLocation
from .core.model import Evidence, evidence_tier


class BehaviorKind(str, Enum):
    PARAMETER = "parameter"
    METADATA = "metadata"
    READ = "read"
    ASSIGNMENT = "assignment"
    MUTATION = "mutation"
    CONDITION = "condition"
    CALL = "call"
    RETURN = "return"
    RAISE = "raise"
    ASSERTION = "assertion"
    TRANSFORM = "transform"
    SIDE_EFFECT = "side_effect"
    MIGRATION = "migration"


@dataclass(frozen=True)
class BehaviorObservation:
    id: str
    symbol_id: str
    kind: BehaviorKind
    summary: str
    location: SourceLocation
    evidence: Evidence
    order: int
    source: str = ""
    condition: Optional[str] = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def confidence_tier(self) -> str:
        return evidence_tier(self.evidence).value

    def to_dict(self, *, include_source: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "symbol_id": self.symbol_id,
            "kind": self.kind.value,
            "summary": self.summary,
            "location": self.location.to_dict(),
            "order": int(self.order),
            "confidence": round(float(self.evidence.confidence), 4),
            "confidence_tier": self.confidence_tier,
            "evidence": self.evidence.to_dict(),
        }
        if include_source and self.source:
            payload["source"] = self.source
        if self.condition:
            payload["condition"] = self.condition
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload


def _compact_source(value: str, limit: int = 320) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _observation_id(
    symbol_id: str, kind: BehaviorKind, location: SourceLocation, summary: str
) -> str:
    raw = "%s|%s|%s|%s|%s|%s" % (
        symbol_id,
        kind.value,
        location.path,
        location.line or 0,
        location.column or 0,
        summary,
    )
    return "behavior:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _target_text(node: ast.AST, source: str) -> str:
    return _compact_source(ast.get_source_segment(source, node) or "", 160)


def _call_name(call: ast.Call, source: str) -> str:
    text = ast.get_source_segment(source, call.func)
    return _compact_source(text or "<call>", 160)


def _is_state_target(node: ast.AST) -> bool:
    return isinstance(node, (ast.Attribute, ast.Subscript))


def _operator(op: ast.AST) -> str:
    mapping = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "//",
        ast.Mod: "%",
        ast.Pow: "**",
        ast.BitAnd: "&",
        ast.BitOr: "|",
        ast.BitXor: "^",
        ast.LShift: "<<",
        ast.RShift: ">>",
    }
    return mapping.get(type(op), type(op).__name__)


class _CallVisitor(ast.NodeVisitor):
    """Collect calls without descending into nested definitions."""

    def __init__(self) -> None:
        self.calls: List[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return


class GroundedBehaviorExtractor:
    """Extract conservative local behavior for already-selected source symbols."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self._text_cache: Dict[str, str] = {}
        self._python_cache: Dict[str, ast.AST] = {}

    def extract(
        self, graph: SemanticGraph, symbol_ids: Sequence[str]
    ) -> List[BehaviorObservation]:
        observations: List[BehaviorObservation] = []
        seen = set()
        for symbol_id in symbol_ids:
            node = graph.node(symbol_id)
            if node is None or node.location is None or not node.location.path:
                continue
            suffix = Path(node.location.path).suffix.casefold()
            if suffix == ".py":
                items = self._extract_python(node)
            elif suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                items = self._extract_javascript(node)
            else:
                items = []
            for item in items:
                if item.id in seen:
                    continue
                seen.add(item.id)
                observations.append(item)
        return sorted(
            observations,
            key=lambda item: (item.location.path, item.order, item.kind.value, item.id),
        )

    def _path(self, relpath: str) -> Path:
        candidate = (self.project_root / relpath).resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError:
            raise ValueError("behavior source escaped project root: %s" % relpath)
        return candidate

    def _text(self, relpath: str) -> str:
        if relpath not in self._text_cache:
            path = self._path(relpath)
            if not path.is_file():
                raise ValueError("behavior source file missing: %s" % relpath)
            self._text_cache[relpath] = path.read_text(encoding="utf-8")
        return self._text_cache[relpath]

    def _python_tree(self, relpath: str) -> ast.AST:
        if relpath not in self._python_cache:
            self._python_cache[relpath] = ast.parse(
                self._text(relpath), filename=relpath
            )
        return self._python_cache[relpath]

    def _python_definition(self, node: SemanticNode) -> Optional[ast.AST]:
        tree = self._python_tree(node.location.path)
        matches: List[ast.AST] = []
        for item in ast.walk(tree):
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if getattr(item, "name", None) != node.name:
                continue
            if node.location.line and getattr(item, "lineno", None) == node.location.line:
                return item
            matches.append(item)
        return matches[0] if len(matches) == 1 else None

    def _make_python(
        self,
        symbol: SemanticNode,
        kind: BehaviorKind,
        stmt: ast.AST,
        summary: str,
        *,
        source: str = "",
        condition: Optional[str] = None,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> BehaviorObservation:
        location = SourceLocation(
            path=symbol.location.path,
            line=getattr(stmt, "lineno", symbol.location.line),
            end_line=getattr(stmt, "end_lineno", getattr(stmt, "lineno", None)),
            column=getattr(stmt, "col_offset", None),
        )
        evidence = Evidence(
            kind=EvidenceKind.STATIC,
            detector="python.ast.behavior",
            detail=summary,
            location=location,
            confidence=1.0,
        )
        return BehaviorObservation(
            id=_observation_id(symbol.id, kind, location, summary),
            symbol_id=symbol.id,
            kind=kind,
            summary=summary,
            location=location,
            evidence=evidence,
            order=(location.line or 0) * 1000 + (location.column or 0),
            source=_compact_source(source),
            condition=condition,
            attributes=dict(attributes or {}),
        )

    def _extract_python(self, symbol: SemanticNode) -> List[BehaviorObservation]:
        definition = self._python_definition(symbol)
        if definition is None:
            return []
        source = self._text(symbol.location.path)
        results: List[BehaviorObservation] = []
        migration = "/migrations/" in ("/" + symbol.location.path.replace("\\", "/"))

        if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = list(definition.args.posonlyargs) + list(definition.args.args)
            positional += list(definition.args.kwonlyargs)
            if definition.args.vararg:
                positional.append(definition.args.vararg)
            if definition.args.kwarg:
                positional.append(definition.args.kwarg)
            for arg in positional:
                annotation = (
                    ast.get_source_segment(source, arg.annotation)
                    if getattr(arg, "annotation", None) is not None
                    else None
                )
                summary = "parameter %s" % arg.arg
                if annotation:
                    summary += ": " + _compact_source(annotation, 120)
                results.append(
                    self._make_python(
                        symbol,
                        BehaviorKind.PARAMETER,
                        arg,
                        summary,
                        source=ast.get_source_segment(source, arg) or arg.arg,
                    )
                )
            for decorator in definition.decorator_list:
                text = _target_text(decorator, source)
                if text:
                    results.append(
                        self._make_python(
                            symbol,
                            BehaviorKind.METADATA,
                            decorator,
                            "decorator @%s" % text,
                            source="@" + text,
                        )
                    )

        body = list(getattr(definition, "body", []))
        self._walk_python_statements(
            symbol, source, body, results, conditions=(), migration=migration
        )
        return results

    def _walk_python_statements(
        self,
        symbol: SemanticNode,
        source: str,
        statements: Sequence[ast.stmt],
        results: List[BehaviorObservation],
        *,
        conditions: Tuple[str, ...],
        migration: bool,
    ) -> None:
        for stmt in statements:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            condition = " and ".join(conditions) if conditions else None
            stmt_source = ast.get_source_segment(source, stmt) or ""

            if isinstance(stmt, ast.If):
                test = _target_text(stmt.test, source)
                results.append(
                    self._make_python(
                        symbol,
                        BehaviorKind.CONDITION,
                        stmt,
                        "if %s" % test,
                        source="if %s" % test,
                        condition=condition,
                    )
                )
                self._emit_python_calls(symbol, source, stmt.test, results, conditions)
                self._walk_python_statements(
                    symbol, source, stmt.body, results,
                    conditions=conditions + ((test or "<condition>"),),
                    migration=migration,
                )
                self._walk_python_statements(
                    symbol, source, stmt.orelse, results,
                    conditions=conditions + (("not (%s)" % test),),
                    migration=migration,
                )
                continue

            if isinstance(stmt, ast.While):
                test = _target_text(stmt.test, source)
                results.append(
                    self._make_python(
                        symbol, BehaviorKind.CONDITION, stmt,
                        "while %s" % test,
                        source="while %s" % test,
                        condition=condition,
                        attributes={"loop": True},
                    )
                )
                self._walk_python_statements(
                    symbol, source, stmt.body, results,
                    conditions=conditions + ((test or "<loop condition>"),),
                    migration=migration,
                )
                self._walk_python_statements(
                    symbol, source, stmt.orelse, results,
                    conditions=conditions, migration=migration,
                )
                continue

            if isinstance(stmt, ast.For):
                target = _target_text(stmt.target, source)
                iterable = _target_text(stmt.iter, source)
                loop_text = "%s in %s" % (target, iterable)
                results.append(
                    self._make_python(
                        symbol, BehaviorKind.CONDITION, stmt,
                        "for %s" % loop_text,
                        source="for %s" % loop_text,
                        condition=condition,
                        attributes={"loop": True},
                    )
                )
                self._emit_python_calls(symbol, source, stmt.iter, results, conditions)
                self._walk_python_statements(
                    symbol, source, stmt.body, results,
                    conditions=conditions + (("for %s" % loop_text),),
                    migration=migration,
                )
                self._walk_python_statements(
                    symbol, source, stmt.orelse, results,
                    conditions=conditions, migration=migration,
                )
                continue

            if isinstance(stmt, ast.Assign):
                value = _target_text(stmt.value, source)
                for target_node in stmt.targets:
                    target = _target_text(target_node, source)
                    kind = BehaviorKind.MUTATION if _is_state_target(target_node) else BehaviorKind.ASSIGNMENT
                    summary = "%s = %s" % (target, value)
                    results.append(
                        self._make_python(
                            symbol, kind, stmt, summary,
                            source=stmt_source, condition=condition,
                            attributes={"migration": migration},
                        )
                    )
                self._emit_python_calls(symbol, source, stmt.value, results, conditions)
                continue

            if isinstance(stmt, ast.AnnAssign):
                target = _target_text(stmt.target, source)
                value = _target_text(stmt.value, source) if stmt.value is not None else "<unset>"
                kind = BehaviorKind.MUTATION if _is_state_target(stmt.target) else BehaviorKind.ASSIGNMENT
                results.append(
                    self._make_python(
                        symbol, kind, stmt, "%s = %s" % (target, value),
                        source=stmt_source, condition=condition,
                        attributes={"migration": migration},
                    )
                )
                if stmt.value is not None:
                    self._emit_python_calls(symbol, source, stmt.value, results, conditions)
                continue

            if isinstance(stmt, ast.AugAssign):
                target = _target_text(stmt.target, source)
                value = _target_text(stmt.value, source)
                summary = "%s %s= %s" % (target, _operator(stmt.op), value)
                results.append(
                    self._make_python(
                        symbol, BehaviorKind.MUTATION, stmt, summary,
                        source=stmt_source, condition=condition,
                        attributes={"migration": migration},
                    )
                )
                self._emit_python_calls(symbol, source, stmt.value, results, conditions)
                continue

            if isinstance(stmt, ast.Return):
                value = _target_text(stmt.value, source) if stmt.value is not None else "None"
                results.append(
                    self._make_python(
                        symbol, BehaviorKind.RETURN, stmt,
                        "return %s" % value,
                        source=stmt_source or ("return %s" % value),
                        condition=condition,
                    )
                )
                if stmt.value is not None:
                    self._emit_python_calls(symbol, source, stmt.value, results, conditions)
                continue

            if isinstance(stmt, ast.Raise):
                value = _target_text(stmt.exc, source) if stmt.exc is not None else "<re-raise>"
                results.append(
                    self._make_python(
                        symbol, BehaviorKind.RAISE, stmt,
                        "raise %s" % value,
                        source=stmt_source or ("raise %s" % value),
                        condition=condition,
                    )
                )
                if stmt.exc is not None:
                    self._emit_python_calls(symbol, source, stmt.exc, results, conditions)
                continue

            if isinstance(stmt, ast.Assert):
                test = _target_text(stmt.test, source)
                results.append(
                    self._make_python(
                        symbol, BehaviorKind.ASSERTION, stmt,
                        "assert %s" % test,
                        source=stmt_source or ("assert %s" % test),
                        condition=condition,
                    )
                )
                self._emit_python_calls(symbol, source, stmt.test, results, conditions)
                continue

            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    text = _target_text(item.context_expr, source)
                    if text:
                        kind = (
                            BehaviorKind.ASSERTION
                            if "raises(" in text or "assert" in text.casefold()
                            else BehaviorKind.METADATA
                        )
                        results.append(
                            self._make_python(
                                symbol, kind, item.context_expr,
                                "with %s" % text,
                                source="with %s" % text,
                                condition=condition,
                            )
                        )
                        self._emit_python_calls(
                            symbol, source, item.context_expr, results, conditions
                        )
                self._walk_python_statements(
                    symbol, source, stmt.body, results,
                    conditions=conditions, migration=migration,
                )
                continue

            if isinstance(stmt, ast.Try):
                self._walk_python_statements(
                    symbol, source, stmt.body, results,
                    conditions=conditions, migration=migration,
                )
                for handler in stmt.handlers:
                    type_text = _target_text(handler.type, source) if handler.type else "Exception"
                    self._walk_python_statements(
                        symbol, source, handler.body, results,
                        conditions=conditions + (("except %s" % type_text),),
                        migration=migration,
                    )
                self._walk_python_statements(
                    symbol, source, stmt.orelse, results,
                    conditions=conditions, migration=migration,
                )
                self._walk_python_statements(
                    symbol, source, stmt.finalbody, results,
                    conditions=conditions, migration=migration,
                )
                continue

            if isinstance(stmt, ast.Expr):
                self._emit_python_calls(symbol, source, stmt.value, results, conditions)

    def _emit_python_calls(
        self,
        symbol: SemanticNode,
        source: str,
        node: ast.AST,
        results: List[BehaviorObservation],
        conditions: Tuple[str, ...],
    ) -> None:
        visitor = _CallVisitor()
        visitor.visit(node)
        condition = " and ".join(conditions) if conditions else None
        effect_names = {
            "save", "delete", "update", "create", "bulk_create", "bulk_update",
            "send", "publish", "emit", "write", "commit", "execute",
        }
        transform_names = {
            "strip", "lower", "upper", "replace", "split", "join", "sort",
            "sorted", "map", "filter", "encode", "decode",
        }
        for call in visitor.calls:
            name = _call_name(call, source)
            call_source = ast.get_source_segment(source, call) or name + "(...)"
            tail = name.rsplit(".", 1)[-1]
            kind = BehaviorKind.CALL
            if tail in effect_names:
                kind = BehaviorKind.SIDE_EFFECT
            elif tail in transform_names:
                kind = BehaviorKind.TRANSFORM
            args = [
                _compact_source(ast.get_source_segment(source, arg) or "", 120)
                for arg in call.args
            ]
            kwargs = {
                kw.arg or "**": _compact_source(
                    ast.get_source_segment(source, kw.value) or "", 120
                )
                for kw in call.keywords
            }
            results.append(
                self._make_python(
                    symbol, kind, call,
                    "call %s" % _compact_source(call_source, 220),
                    source=call_source,
                    condition=condition,
                    attributes={"callee": name, "arguments": args, "keywords": kwargs},
                )
            )

    def _extract_javascript(self, symbol: SemanticNode) -> List[BehaviorObservation]:
        text = self._text(symbol.location.path)
        lines = text.splitlines()
        start = max(1, int(symbol.location.line or 1))
        end = int(symbol.location.end_line or start)
        end = min(max(start, end), len(lines))
        segment = lines[start - 1 : end]
        results: List[BehaviorObservation] = []
        active_conditions: List[str] = []
        detector = "javascript.source.behavior"

        def make(kind: BehaviorKind, line_no: int, raw: str, summary: str, **attrs: Any) -> None:
            location = SourceLocation(path=symbol.location.path, line=line_no, end_line=line_no)
            evidence = Evidence(
                kind=EvidenceKind.STATIC,
                detector=detector,
                detail=summary,
                location=location,
                confidence=0.96,
            )
            results.append(
                BehaviorObservation(
                    id=_observation_id(symbol.id, kind, location, summary),
                    symbol_id=symbol.id,
                    kind=kind,
                    summary=summary,
                    location=location,
                    evidence=evidence,
                    order=line_no * 1000,
                    source=_compact_source(raw),
                    condition=" and ".join(active_conditions) if active_conditions else None,
                    attributes=attrs,
                )
            )

        call_pattern = re.compile(r"(?<!function\s)([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
        for offset, raw in enumerate(segment):
            line_no = start + offset
            stripped = raw.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if_match = re.search(r"\bif\s*\((.+)\)", stripped)
            if if_match:
                cond = _compact_source(if_match.group(1), 220)
                make(BehaviorKind.CONDITION, line_no, raw, "if %s" % cond)
                active_conditions = [cond]
            return_match = re.search(r"\breturn\s+(.+?);?\s*$", stripped)
            if return_match:
                value = _compact_source(return_match.group(1).rstrip(";"), 220)
                make(BehaviorKind.RETURN, line_no, raw, "return %s" % value)
            throw_match = re.search(r"\bthrow\s+(.+?);?\s*$", stripped)
            if throw_match:
                value = _compact_source(throw_match.group(1).rstrip(";"), 220)
                make(BehaviorKind.RAISE, line_no, raw, "throw %s" % value)
            assertion = re.search(r"\b(?:expect|assert)\s*\((.+)", stripped)
            if assertion:
                make(BehaviorKind.ASSERTION, line_no, raw, _compact_source(stripped, 240))
            aug = re.search(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*([+\-*/])=\s*(.+?);?\s*$", stripped)
            if aug:
                make(
                    BehaviorKind.MUTATION, line_no, raw,
                    "%s %s= %s" % (aug.group(1), aug.group(2), _compact_source(aug.group(3).rstrip(";"), 160)),
                )
            elif "==" not in stripped and "=>" not in stripped:
                assignment = re.search(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*=\s*(.+?);?\s*$", stripped)
                if assignment and not stripped.startswith(("function ", "export function ")):
                    target = assignment.group(1)
                    kind = BehaviorKind.MUTATION if "." in target else BehaviorKind.ASSIGNMENT
                    make(
                        kind, line_no, raw,
                        "%s = %s" % (target, _compact_source(assignment.group(2).rstrip(";"), 180)),
                    )
            for match in call_pattern.finditer(stripped):
                name = match.group(1)
                if name in {"if", "for", "while", "switch", "function"}:
                    continue
                kind = BehaviorKind.CALL
                tail = name.rsplit(".", 1)[-1]
                if tail in {"trim", "toUpperCase", "toLowerCase", "replace", "map", "filter"}:
                    kind = BehaviorKind.TRANSFORM
                elif tail in {"save", "delete", "update", "send", "publish", "emit", "write"}:
                    kind = BehaviorKind.SIDE_EFFECT
                make(kind, line_no, raw, "call %s" % name, callee=name)
            if stripped.startswith("}"):
                active_conditions = []
        return results
