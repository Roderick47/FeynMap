import ast

from feynmap import FeynMapEngine
from feynmap.adapters.python import _ScopedBodyCollector
from feynmap.adapters.python_source import (
    PythonSourceSession,
    get_python_source_session,
    python_source_session,
)


def test_engine_parses_each_python_file_once_across_all_python_passes(monkeypatch, tmp_path):
    (tmp_path / "package").mkdir()
    (tmp_path / "package" / "__init__.py").write_text(
        "from .service import Service\n"
        "__all__ = ['Service']\n",
        encoding="utf-8",
    )
    (tmp_path / "package" / "service.py").write_text(
        "class Service:\n"
        "    def run(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from package import Service\n"
        "\n"
        "class App:\n"
        "    def __init__(self, service: Service):\n"
        "        self.service = service\n"
        "\n"
        "    def execute(self):\n"
        "        return self.service.run()\n",
        encoding="utf-8",
    )

    original = ast.parse
    calls = []

    def counting_parse(source, *args, **kwargs):
        calls.append(kwargs.get("filename") or (args[0] if args else None))
        return original(source, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", counting_parse)

    graph = FeynMapEngine().analyze(str(tmp_path))

    assert len(calls) == 3
    assert graph.find("Service")
    assert graph.find("App.execute")


def test_active_source_session_is_reused_and_scoped(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")

    outside = get_python_source_session(tmp_path)
    assert isinstance(outside, PythonSourceSession)

    with python_source_session(tmp_path) as active:
        assert get_python_source_session(tmp_path) is active
        first = active.record(path)
        second = active.record(path)
        assert first is second
        assert first.tree is not None

    assert get_python_source_session(tmp_path) is not active


def test_repository_import_index_is_shared_within_session(monkeypatch, tmp_path):
    (tmp_path / "one.py").write_text("import flask\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")

    with python_source_session(tmp_path) as source:
        first = source.imports_by_file()

        def fail_walk(*args, **kwargs):
            raise AssertionError("cached import index should not walk ASTs again")

        monkeypatch.setattr(ast, "walk", fail_walk)
        second = source.imports_by_file()
        combined = source.repository_imports()

    assert first == second
    assert "flask" in combined
    assert "fastapi" in combined



def test_ast_index_is_reused_across_consumers(monkeypatch, tmp_path):
    path = tmp_path / "mod.py"
    path.write_text(
        "import os\n"
        "def work():\n"
        "    print(os.getenv('X'))\n",
        encoding="utf-8",
    )

    with python_source_session(tmp_path) as source:
        record = source.record(path)
        original_walk = ast.walk
        calls = {"count": 0}

        def counting_walk(node):
            calls["count"] += 1
            return original_walk(node)

        monkeypatch.setattr(ast, "walk", counting_walk)
        first = source.ast_index(record.path)
        second = source.ast_index(record.path)
        imports = source.imports_by_file()

    assert first is second
    assert calls["count"] == 1
    assert len(first.calls) == 2
    assert "os" in imports["mod.py"]


def test_scoped_callable_cache_preserves_nested_callable_boundaries(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text(
        "def outer():\n"
        "    top()\n"
        "    def inner():\n"
        "        hidden()\n"
        "    lambda: also_hidden()\n"
        "    return done()\n",
        encoding="utf-8",
    )

    with python_source_session(tmp_path) as source:
        record = source.record(path)
        assert record.tree is not None
        outer = record.tree.body[0]

        first_calls, first_awaits = source.scoped_callable(outer)
        second_calls, second_awaits = source.scoped_callable(outer)

    def call_name(call):
        return call.func.id if isinstance(call.func, ast.Name) else ""

    assert [call_name(call) for call in first_calls] == ["top", "done"]
    assert first_awaits == ()
    assert first_calls is second_calls
    assert first_awaits is second_awaits



def test_indexed_scoped_traversal_matches_historical_collector_order(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text(
        "async def outer(flag):\n"
        "    first(one(), two())\n"
        "    if flag:\n"
        "        await third()\n"
        "    def inner():\n"
        "        hidden()\n"
        "    class Inner:\n"
        "        value = class_hidden()\n"
        "    (lambda: lambda_hidden())\n"
        "    return final()\n",
        encoding="utf-8",
    )

    with python_source_session(tmp_path) as source:
        record = source.record(path)
        assert record.tree is not None
        outer = record.tree.body[0]
        source.ast_index(path)

        historical = _ScopedBodyCollector(outer)
        historical.visit(outer)
        indexed_calls, indexed_awaits = source.scoped_callable(outer)

    assert indexed_calls == tuple(historical.calls)
    assert indexed_awaits == tuple(historical.awaits)


def test_full_ast_index_preserves_ast_walk_order(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text(
        "def first():\n"
        "    alpha(beta())\n"
        "def second():\n"
        "    gamma()\n",
        encoding="utf-8",
    )

    with python_source_session(tmp_path) as source:
        record = source.record(path)
        assert record.tree is not None
        expected_calls = tuple(
            node for node in ast.walk(record.tree) if isinstance(node, ast.Call)
        )
        indexed_calls = source.ast_index(path).calls

    assert indexed_calls == expected_calls
