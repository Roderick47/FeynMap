"""Regression checks from post-S6 external review: minified JS must not crash analysis."""
from __future__ import annotations

from pathlib import Path

from feynmap.adapters.javascript import JavaScriptAdapter
from feynmap.core import NodeKind


def test_vendored_minified_js_is_skipped_but_first_party_js_remains(tmp_path: Path):
    static = tmp_path / "static" / "vendor"
    static.mkdir(parents=True)
    # Former path|name|line IDs collide when same-named declarations share a line.
    (static / "jquery.min.js").write_text(
        "function same(){}function same(){}function same(){}",
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text(
        "function routePage() { return 1; }\n",
        encoding="utf-8",
    )

    graph = JavaScriptAdapter().analyze(tmp_path)
    assert graph.node("javascript:module:app.js") is not None
    assert graph.node("javascript:module:static/vendor/jquery.min.js") is None
    assert any(
        "skipped minified JavaScript: static/vendor/jquery.min.js" in item
        for item in graph.diagnostics.get("warnings", [])
    )
    assert any(
        node.name == "routePage" and node.kind == NodeKind.FUNCTION
        for node in graph.nodes
    )


def test_same_name_same_line_js_declarations_have_unique_stable_ids(tmp_path: Path):
    (tmp_path / "compact.js").write_text(
        "function repeat(){}function repeat(){}function repeat(){}\n",
        encoding="utf-8",
    )
    adapter = JavaScriptAdapter()
    first = adapter.analyze(tmp_path)
    second = adapter.analyze(tmp_path)
    functions = [
        node for node in first.nodes
        if node.kind == NodeKind.FUNCTION and node.name == "repeat"
    ]
    assert len(functions) == 3
    assert len({node.id for node in functions}) == 3
    assert sorted(node.id for node in functions) == sorted(
        node.id for node in second.nodes
        if node.kind == NodeKind.FUNCTION and node.name == "repeat"
    )
    assert sum(
        "disambiguated same-line JavaScript symbol repeat" in item
        for item in first.diagnostics.get("warnings", [])
    ) == 2


def test_unambiguous_js_symbol_preserves_historical_identity(tmp_path: Path):
    (tmp_path / "app.js").write_text("function alpha() {}\n", encoding="utf-8")
    adapter = JavaScriptAdapter()
    graph = adapter.analyze(tmp_path)
    symbol = next(node for node in graph.nodes if node.name == "alpha")
    assert symbol.id == adapter._id("app.js", "alpha", 1)
