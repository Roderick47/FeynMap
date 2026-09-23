"""Framework-neutral integration boundary extraction for Python source."""
from __future__ import annotations

import ast
import heapq
import shlex
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import add_contract

from .python_source import get_python_source_session

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".feynmap"}
HTTP_ROOTS = {"requests", "httpx"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
PROCESS_APIS = {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.Popen", "os.system"}
READ_MODES = {"r", "rb", "rt", "r+", "rb+", "r+b"}


def enrich_python_boundaries(graph: SemanticGraph, root: Path) -> SemanticGraph:
    """Attach non-framework integration contracts to Python semantic nodes.

    Graph nodes are indexed once up front. The previous implementation scanned
    every graph node for every ast.Call, which becomes effectively quadratic on
    large repositories such as SymPy and Astropy.
    """
    modules_by_path, owners_by_path = _build_boundary_index(graph)
    source = get_python_source_session(root)
    for record in source.records():
        if record.tree is None:
            continue
        path = record.path
        relative = record.relative
        tree = record.tree
        module = modules_by_path.get(relative)
        if module and _has_main_guard(tree):
            add_contract(module, "cli_entrypoint", relative, 0.98, aliases=[path.name])

        calls = list(source.ast_index(record.path).calls)
        owners = _owners_for_lines(
            owners_by_path.get(relative, ()),
            [getattr(call, "lineno", 1) for call in calls],
        )
        for call in calls:
            owner = owners.get(getattr(call, "lineno", 1)) or module
            if owner is None:
                continue
            name = _expr_name(call.func)
            short = name.rsplit(".", 1)[-1]
            root_name = name.split(".", 1)[0]

            if root_name in HTTP_ROOTS and short.lower() in HTTP_METHODS and call.args:
                target = _string(call.args[0])
                if target:
                    add_contract(owner, "http_client", target, 0.98, method=short.upper(), line=getattr(call, "lineno", 1))
                continue

            if name in {"urllib.request.urlopen"} and call.args:
                target = _string(call.args[0])
                if target:
                    add_contract(owner, "http_client", target, 0.94, method="GET", line=getattr(call, "lineno", 1))
                continue

            if name in {"websockets.connect", "websocket.create_connection"} and call.args:
                target = _string(call.args[0])
                if target:
                    add_contract(owner, "websocket_client", target, 0.96, line=getattr(call, "lineno", 1))
                continue

            if name in PROCESS_APIS and call.args:
                target = _command_target(call.args[0])
                if target:
                    add_contract(owner, "process_spawn", target, 0.94, api=name, line=getattr(call, "lineno", 1))
                continue

            if name == "open" and call.args:
                target = _string(call.args[0])
                if target:
                    mode = _string(call.args[1]) if len(call.args) > 1 else "r"
                    for keyword in call.keywords:
                        if keyword.arg == "mode":
                            mode = _string(keyword.value) or mode
                    kind = "file_read" if str(mode or "r") in READ_MODES and not any(flag in str(mode) for flag in ("w", "a", "x")) else "file_write"
                    add_contract(owner, kind, target, 0.98, mode=mode or "r", line=getattr(call, "lineno", 1))
                continue

            if name in {"os.getenv", "os.environ.get"} and call.args:
                key = _string(call.args[0])
                if key:
                    add_contract(owner, "config_read", "env:%s" % key, 0.99, line=getattr(call, "lineno", 1))
                continue

            if name in {"sqlite3.connect", "psycopg.connect", "psycopg2.connect", "sqlalchemy.create_engine"} and call.args:
                target = _string(call.args[0])
                if target:
                    add_contract(owner, "database_client", target, 0.93, api=name, line=getattr(call, "lineno", 1))
                continue

            if name in {"ctypes.CDLL", "ctypes.PyDLL", "cffi.dlopen"} and call.args:
                target = _string(call.args[0])
                if target:
                    add_contract(owner, "ffi_import", target, 0.96, api=name, line=getattr(call, "lineno", 1))
                continue

            if short in {"publish", "send"} and call.args:
                target = _string(call.args[0])
                if target and ("redis" in name.lower() or "producer" in name.lower() or "kafka" in name.lower()):
                    add_contract(owner, "queue_publish", target, 0.72, api=name, line=getattr(call, "lineno", 1))

    return graph


def _build_boundary_index(
    graph: SemanticGraph,
) -> Tuple[Dict[str, SemanticNode], Dict[str, List[SemanticNode]]]:
    """Index Python modules and callable owners by source path in one graph pass."""
    modules: Dict[str, SemanticNode] = {}
    owners: Dict[str, List[SemanticNode]] = {}
    owner_kinds = {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.HANDLER}
    for node in graph.nodes:
        if node.language != "python" or not node.location or not node.location.path:
            continue
        path = node.location.path
        if node.kind == NodeKind.MODULE:
            modules.setdefault(path, node)
        elif node.kind in owner_kinds:
            owners.setdefault(path, []).append(node)
    # Keep graph insertion order inside each path. The owner sweep records
    # that order as its stable tie-breaker, matching the historical resolver.
    return modules, owners


def _owners_for_lines(
    nodes: Sequence[SemanticNode],
    lines: Sequence[int],
) -> Dict[int, SemanticNode]:
    """Resolve call-line owners with a sweep instead of repeated graph scans.

    Semantics match the historical resolver:
    1. choose the smallest callable span that contains the line;
    2. otherwise choose the callable with the latest start at/before the line.
    """
    if not nodes or not lines:
        return {}

    indexed = []
    for order, node in enumerate(nodes):
        location = node.location
        if location is None:
            continue
        start = location.line or 1
        end = location.end_line
        span = (end - start) if end is not None else 2 ** 31
        indexed.append((start, end, span, order, node))
    indexed.sort(key=lambda item: (item[0], item[3]))

    result: Dict[int, SemanticNode] = {}
    active: List[Tuple[int, int, int, SemanticNode]] = []
    position = 0
    latest_preceding: Optional[Tuple[int, int, SemanticNode]] = None

    for line in sorted(set(int(value or 1) for value in lines)):
        while position < len(indexed) and indexed[position][0] <= line:
            start, end, span, order, node = indexed[position]
            if (
                latest_preceding is None
                or start > latest_preceding[0]
                or (start == latest_preceding[0] and order < latest_preceding[1])
            ):
                latest_preceding = (start, order, node)
            if end is not None:
                heapq.heappush(active, (span, order, end, node))
            position += 1

        while active and active[0][2] < line:
            heapq.heappop(active)

        if active:
            result[line] = active[0][3]
        elif latest_preceding is not None:
            result[line] = latest_preceding[2]

    return result


def _module_for_path(graph: SemanticGraph, path: str) -> Optional[SemanticNode]:
    """Compatibility helper for callers outside the optimized enrichment path."""
    return _build_boundary_index(graph)[0].get(path)


def _node_for_line(graph: SemanticGraph, path: str, line: int) -> Optional[SemanticNode]:
    """Compatibility helper retaining the historical single-line API."""
    owners = _build_boundary_index(graph)[1].get(path, ())
    return _owners_for_lines(owners, [line]).get(line)


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        left = node.test.left
        comparators = node.test.comparators
        if isinstance(left, ast.Name) and left.id == "__name__" and comparators and _string(comparators[0]) == "__main__":
            return True
    return False


def _command_target(node: ast.AST) -> Optional[str]:
    direct = _string(node)
    if direct:
        try:
            parts = shlex.split(direct)
        except ValueError:
            parts = direct.split()
        return _best_command_part(parts)
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [value for value in (_string(item) for item in node.elts) if value]
        return _best_command_part(values)
    return None


def _best_command_part(parts: List[str]) -> Optional[str]:
    if not parts:
        return None
    for value in parts[1:]:
        if value.endswith((".py", ".js", ".mjs", ".cjs", ".sh", ".rb", ".jar", ".exe")):
            return value
    return parts[0]


def _expr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _expr_name(node.value)
        return "%s.%s" % (left, node.attr) if left else node.attr
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    return ""


def _string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Str):
        return node.s
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in EXCLUDED for part in parts):
            continue
        yield path
