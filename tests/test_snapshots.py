import json
from pathlib import Path

from feynmap.cli import main
from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from feynmap.snapshots import SnapshotStore, capture_repository_snapshot, repository_locator


def _graph():
    location = SourceLocation("app.py", 1)
    evidence = Evidence(EvidenceKind.STATIC, "test.fixture", "fixture evidence", location, 1.0)
    module = SemanticNode(
        id="python:module:app",
        name="app",
        qualified_name="app",
        kind=NodeKind.MODULE,
        language="python",
        location=location,
        evidence=[evidence],
    )
    function = SemanticNode(
        id="python:symbol:app.run",
        name="run",
        qualified_name="app.run",
        kind=NodeKind.FUNCTION,
        language="python",
        location=SourceLocation("app.py", 3),
        attributes={"python": {"parameters": []}},
        evidence=[evidence],
    )
    edge = SemanticEdge(
        id="edge:test",
        source=module.id,
        target=function.id,
        kind=EdgeKind.CONTAINS,
        confidence=1.0,
        evidence=[evidence],
    )
    return SemanticGraph(
        nodes=[module, function],
        edges=[edge],
        metadata={"language_selection": "python", "framework_selection": "none"},
        diagnostics={"errors": [], "warnings": ["fixture warning"]},
    )


def test_semantic_graph_roundtrips_from_serialized_form():
    graph = _graph()
    payload = graph.to_dict()

    restored = SemanticGraph.from_dict(payload)

    assert payload["diagnostics"]["warnings"] == ["fixture warning"]
    assert restored.to_dict() == payload
    assert restored.diagnostics["warnings"] == ["fixture warning"]
    assert restored.node("python:symbol:app.run").qualified_name == "app.run"
    assert restored.edges[0].kind == EdgeKind.CONTAINS
    assert restored.edges[0].evidence[0].kind == EvidenceKind.STATIC


def test_snapshot_identity_is_stable_and_changes_with_repository_content(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    graph = _graph()

    first = capture_repository_snapshot(tmp_path, graph, created_at="2026-01-01T00:00:00+00:00")
    second = capture_repository_snapshot(tmp_path, graph, created_at="2026-01-02T00:00:00+00:00")

    assert first.snapshot_id == second.snapshot_id
    assert first.content_hash == second.content_hash
    assert first.graph_hash == second.graph_hash

    (tmp_path / "app.py").write_text("def run():\n    return 2\n", encoding="utf-8")
    changed = capture_repository_snapshot(tmp_path, graph)

    assert changed.content_hash != first.content_hash
    assert changed.snapshot_id != first.snapshot_id


def test_sqlite_store_roundtrips_graph_and_current_pointer(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    graph = _graph()
    store = SnapshotStore(tmp_path / ".feynmap" / "snapshots.sqlite")
    snapshot = capture_repository_snapshot(tmp_path, graph)

    store.save(snapshot, graph)
    loaded_snapshot, loaded_graph = store.load(snapshot.snapshot_id)

    assert loaded_snapshot.snapshot_id == snapshot.snapshot_id
    assert loaded_snapshot.content_hash == snapshot.content_hash
    assert loaded_graph.to_dict() == graph.to_dict()
    assert loaded_graph.diagnostics["warnings"] == ["fixture warning"]
    assert store.current_snapshot_id(snapshot.repository_key) == snapshot.snapshot_id
    assert store.load_current(snapshot.repository_key)[0].snapshot_id == snapshot.snapshot_id
    assert store.list_snapshots(snapshot.repository_key)[0]["snapshot_id"] == snapshot.snapshot_id

    recaptured = capture_repository_snapshot(tmp_path, graph)
    assert recaptured.content_hash == snapshot.content_hash
    assert recaptured.snapshot_id == snapshot.snapshot_id


def test_snapshot_cli_persists_current_repository_graph(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    result = main(["snapshot", str(tmp_path), "--language", "python", "--framework", "none"])
    output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert output["current"] is True
    assert output["analysis_options"] == {
        "language_selection": "python",
        "framework_selection": "none",
    }
    assert output["file_count"] == 1
    store_path = tmp_path / ".feynmap" / "snapshots.sqlite"
    assert store_path.exists()

    store = SnapshotStore(store_path)
    loaded_snapshot, loaded_graph = store.load(output["snapshot_id"])
    assert loaded_snapshot.snapshot_id == output["snapshot_id"]
    assert store.current_snapshot_id(loaded_snapshot.repository_key) == loaded_snapshot.snapshot_id
    assert any(node.qualified_name == "app.run" for node in loaded_graph.nodes)


def test_git_origin_locator_is_sanitized(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("0123456789abcdef\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = https://secret-token@example.com/owner/repo.git\n',
        encoding="utf-8",
    )

    locator = repository_locator(tmp_path)

    assert locator == "https://example.com/owner/repo.git"
    assert "secret-token" not in locator
