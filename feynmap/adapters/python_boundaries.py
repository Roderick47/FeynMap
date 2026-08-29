"""Framework-neutral integration boundary extraction for Python source."""
from __future__ import annotations

import ast
import shlex
from pathlib import Path
from typing import Iterable, List, Optional

from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import add_contract

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox"}
HTTP_ROOTS = {"requests", "httpx"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
PROCESS_APIS = {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.Popen", "os.system"}
READ_MODES = {"r", "rb", "rt", "r+", "rb+", "r+b"}


def enrich_python_boundaries(graph: SemanticGraph, root: Path) -> SemanticGraph:
    """Attach non-framework integration contracts to Python semantic nodes."""
    for path in _iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        module = _module_for_path(graph, relative)
        if module and _has_main_guard(tree):
            add_contract(module, "cli_entrypoint", relative, 0.98, aliases=[path.name])

        for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
            owner = _node_for_line(graph, relative, getattr(call, "lineno", 1)) or module
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


def _module_for_path(graph: SemanticGraph, path: str) -> Optional[SemanticNode]:
    for node in graph.nodes:
        if node.language == "python" and node.kind == NodeKind.MODULE and node.location and node.location.path == path:
            return node
    return None


def _node_for_line(graph: SemanticGraph, path: str, line: int) -> Optional[SemanticNode]:
    exact: List[SemanticNode] = []
    preceding: List[SemanticNode] = []
    for node in graph.nodes:
        if node.language != "python" or not node.location or node.location.path != path:
            continue
        if node.kind not in {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.HANDLER}:
            continue
        start = node.location.line or 1
        end = node.location.end_line
        if end is not None and start <= line <= end:
            exact.append(node)
        elif start <= line:
            preceding.append(node)
    if exact:
        exact.sort(key=lambda item: (item.location.end_line or item.location.line or 1) - (item.location.line or 1))
        return exact[0]
    if preceding:
        preceding.sort(key=lambda item: item.location.line or 1, reverse=True)
        return preceding[0]
    return None


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
