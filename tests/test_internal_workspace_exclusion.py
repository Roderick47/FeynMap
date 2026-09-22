from feynmap import FeynMapEngine


def test_internal_feynmap_workspace_is_ignored_by_auto_language_detection(tmp_path):
    (tmp_path / "app.py").write_text(
        "def visible():\n    return 1\n",
        encoding="utf-8",
    )

    workspace = tmp_path / ".feynmap" / "r1" / "swebench" / "checkouts" / "nested"
    workspace.mkdir(parents=True)
    (workspace / "hidden.py").write_text(
        "def hidden_python():\n    return 2\n",
        encoding="utf-8",
    )
    (workspace / "hidden.js").write_text(
        "function hiddenJavaScript() { return 3; }\n",
        encoding="utf-8",
    )
    (workspace / "hidden.html").write_text(
        "<html><body>hidden</body></html>\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), framework="none")

    assert graph.metadata["language_names"] == ["python"]
    locations = {
        node.location.path
        for node in graph.nodes
        if node.location is not None
    }
    assert "app.py" in locations
    assert not any(path.startswith(".feynmap/") for path in locations)
    assert graph.find("visible")
    assert not graph.find("hidden_python")


def test_internal_feynmap_workspace_is_ignored_by_python_enrichment(tmp_path):
    (tmp_path / "app.py").write_text(
        "def visible():\n"
        "    open('visible.txt')\n",
        encoding="utf-8",
    )
    workspace = tmp_path / ".feynmap" / "cache"
    workspace.mkdir(parents=True)
    (workspace / "hidden.py").write_text(
        "def hidden():\n"
        "    open('hidden.txt')\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(
        str(tmp_path),
        language="python",
        framework="none",
    )

    visible = graph.find("visible")[0]
    contracts = visible.attributes.get("integration_contracts") or []
    assert any(
        item.get("kind") == "file_read" and item.get("target") == "visible.txt"
        for item in contracts
    )
    assert not graph.find("hidden")
    assert all(
        "hidden.txt" != item.get("target")
        for node in graph.nodes
        for item in (node.attributes.get("integration_contracts") or [])
        if isinstance(item, dict)
    )
