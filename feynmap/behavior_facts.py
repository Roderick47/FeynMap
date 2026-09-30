"""Compact structured facts derived from a behavioral source witness.

These facts are additive metadata on an already source-backed observation.
They are not new semantic-graph truth and never alter confidence tiers.
"""
from __future__ import annotations

import ast
import io
import keyword
import re
import token
import tokenize
from typing import Any, Dict, List, Mapping, Sequence, Set

from .behavior import BehaviorObservation


_PY_OPERATOR_NAMES = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
    ast.Gt: ">", ast.GtE: ">=", ast.In: "in", ast.NotIn: "not in",
    ast.Is: "is", ast.IsNot: "is not", ast.And: "and", ast.Or: "or",
    ast.Not: "not", ast.USub: "-", ast.UAdd: "+",
}

_JS_KEYWORDS = {
    "if", "else", "for", "while", "switch", "case", "return", "throw",
    "function", "export", "default", "import", "from", "const", "let", "var",
    "true", "false", "null", "undefined", "new", "await", "async", "class",
    "extends", "this", "typeof", "instanceof", "in", "of",
}

_TRANSFORM_NAMES = {
    "strip", "trim", "lower", "upper", "toLowerCase", "toUpperCase",
    "replace", "split", "join", "map", "filter", "encode", "decode",
    "String", "Number", "Boolean", "int", "float", "str", "bool",
}


def _unique(values: Sequence[Any], limit: int = 24) -> List[Any]:
    result: List[Any] = []
    seen = set()
    for value in values:
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _python_parseable(source: str) -> str:
    text = str(source or "").strip()
    if not text:
        return ""
    # Condition observations intentionally use compact source such as
    # `if x > 1`; make only that witness parseable without changing meaning.
    if re.match(r"^(?:if|while|for|with)\b", text) and ":" not in text.splitlines()[0]:
        return text + ":\n    pass"
    if text.startswith("@"):
        return text + "\ndef _feynmap_behavior_probe():\n    pass"
    return text


def _python_facts(source: str) -> Dict[str, Any]:
    text = _python_parseable(source)
    if not text:
        return {}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return _python_token_facts(source)

    reads: List[str] = []
    literals: List[Any] = []
    operators: List[str] = []
    transforms: List[str] = []
    calls: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            segment = ast.get_source_segment(text, node)
            if segment:
                reads.append(segment)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            reads.append(node.id)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool)) or node.value is None:
                literals.append(node.value)
        elif isinstance(node, ast.Call):
            callee = ast.get_source_segment(text, node.func)
            if callee:
                calls.append(callee)
                tail = callee.rsplit(".", 1)[-1]
                if tail in _TRANSFORM_NAMES:
                    transforms.append(tail)
        else:
            name = _PY_OPERATOR_NAMES.get(type(node))
            if name:
                operators.append(name)

    result: Dict[str, Any] = {}
    if reads:
        result["reads"] = _unique(reads)
    if literals:
        result["literals"] = _unique(literals)
    if operators:
        result["operators"] = _unique(operators)
    if calls:
        result["calls"] = _unique(calls)
    if transforms:
        result["transforms"] = _unique(transforms)
    return result


def _python_token_facts(source: str) -> Dict[str, Any]:
    names: List[str] = []
    literals: List[Any] = []
    try:
        stream = tokenize.generate_tokens(io.StringIO(str(source or "")).readline)
        for item in stream:
            if item.type == token.NAME and not keyword.iskeyword(item.string):
                names.append(item.string)
            elif item.type == token.STRING:
                try:
                    value = ast.literal_eval(item.string)
                except Exception:
                    value = item.string
                literals.append(value)
            elif item.type == token.NUMBER:
                try:
                    value = ast.literal_eval(item.string)
                except Exception:
                    value = item.string
                literals.append(value)
    except (tokenize.TokenError, IndentationError):
        pass
    result: Dict[str, Any] = {}
    if names:
        result["reads"] = _unique(names)
    if literals:
        result["literals"] = _unique(literals)
    return result


def _javascript_facts(source: str) -> Dict[str, Any]:
    text = str(source or "")
    if not text:
        return {}
    string_pattern = re.compile(r"(?P<quote>['\"`])(?P<body>(?:\\.|(?!\1).)*)(?P=quote)")
    literals: List[Any] = [match.group("body") for match in string_pattern.finditer(text)]
    literals.extend(
        match.group(0)
        for match in re.finditer(r"(?<![\w$])(?:\d+(?:\.\d+)?)(?![\w$])", text)
    )
    identifiers = [
        match.group(0)
        for match in re.finditer(r"[A-Za-z_$][A-Za-z0-9_$]*", text)
        if match.group(0) not in _JS_KEYWORDS
    ]
    calls = [
        match.group(1)
        for match in re.finditer(
            r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(", text
        )
        if match.group(1) not in {"if", "for", "while", "switch", "function"}
    ]
    transforms = [
        name.rsplit(".", 1)[-1]
        for name in calls
        if name.rsplit(".", 1)[-1] in _TRANSFORM_NAMES
    ]
    operators = [
        match.group(0)
        for match in re.finditer(r"===|!==|==|!=|<=|>=|=>|&&|\|\||[<>+\-*/]", text)
    ]
    result: Dict[str, Any] = {}
    if identifiers:
        result["reads"] = _unique(identifiers)
    if literals:
        result["literals"] = _unique(literals)
    if calls:
        result["calls"] = _unique(calls)
    if transforms:
        result["transforms"] = _unique(transforms)
    if operators:
        result["operators"] = _unique(operators)
    return result


def structured_behavior_facts(observation: BehaviorObservation) -> Mapping[str, Any]:
    """Return compact source-backed expression facts for one observation."""
    source = observation.source or observation.summary
    path = observation.location.path.casefold()
    if path.endswith(".py"):
        return _python_facts(source)
    if path.endswith((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")):
        return _javascript_facts(source)
    return {}
