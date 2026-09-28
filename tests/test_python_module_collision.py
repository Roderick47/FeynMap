from pathlib import Path

from feynmap.adapters.python import PythonAdapter


def test_root_init_does_not_duplicate_same_named_nested_package(tmp_path: Path):
    package_name = tmp_path.name
    (tmp_path / "__init__.py").write_text("ROOT = True\n", encoding="utf-8")
    package = tmp_path / package_name
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "mod.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    graph = PythonAdapter().analyze(tmp_path)

    module_id = "python:module:%s" % package_name
    matches = [node for node in graph.nodes if node.id == module_id]
    assert len(matches) == 1
    assert matches[0].location.path == "%s/__init__.py" % package_name
    assert any(
        "shadowed duplicate Python module %s" % package_name in warning
        for warning in graph.diagnostics["warnings"]
    )
