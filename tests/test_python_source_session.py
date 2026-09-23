import ast

from feynmap import FeynMapEngine
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
