import json
from pathlib import Path

import pytest

from feynmap import FeynMapEngine
from feynmap.cli import main
from feynmap.diff import diff_snapshots, diff_store_snapshots
from feynmap.snapshots import SnapshotStore, capture_repository_snapshot


def _fake_git(root: Path, origin: str = "https://example.com/owner/repo.git") -> None:
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = %s\n' % origin,
        encoding="utf-8",
    )


def _analyze(root: Path):
    return FeynMapEngine().analyze(str(root), language="python", framework="none")


def _stored_pair(root: Path):
    _fake_git(root)
    app = root / "app.py"
    app.write_text("def run():\n    return 1\n", encoding="utf-8")
    store = SnapshotStore(root / ".feynmap" / "snapshots.sqlite")

    before_graph = _analyze(root)
    before_snapshot = capture_repository_snapshot(root, before_graph)
    store.save(before_snapshot, before_graph)

    app.write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    after_graph = _analyze(root)
    after_snapshot = capture_repository_snapshot(root, after_graph)
    store.save(after_snapshot, after_graph)
    return store, before_snapshot, after_snapshot


def test_snapshot_diff_reports_file_and_semantic_changes(tmp_path: Path):
    store, before_snapshot, after_snapshot = _stored_pair(tmp_path)

    delta = diff_store_snapshots(store, before_snapshot.snapshot_id, after_snapshot.snapshot_id)

    assert delta["content_changed"] is True
    assert delta["graph_changed"] is True
    assert delta["files"]["modified"] == ["app.py"]
    assert delta["files"]["added"] == []
    assert delta["files"]["removed"] == []

    added_nodes = {
        item.get("qualified_name")
        for item in delta["semantic"]["nodes"]["added"]
    }
    assert "app.helper" in added_nodes

    added_relationship_keys = {
        item["key"]
        for item in delta["semantic"]["relationships"]["added"]
    }
    assert "python:symbol:app.run|calls|python:symbol:app.helper" in added_relationship_keys


def test_snapshot_diff_cli_loads_stored_graphs_without_reanalysis(tmp_path: Path, capsys):
    store, before_snapshot, after_snapshot = _stored_pair(tmp_path)

    result = main(
        [
            "diff",
            before_snapshot.snapshot_id,
            after_snapshot.snapshot_id,
            "--store",
            str(store.path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["before_snapshot_id"] == before_snapshot.snapshot_id
    assert payload["after_snapshot_id"] == after_snapshot.snapshot_id
    assert payload["files"]["modified"] == ["app.py"]
    assert payload["semantic"]["nodes"]["added_count"] >= 1


def test_snapshot_diff_rejects_different_repositories(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _fake_git(first, "https://example.com/owner/first.git")
    _fake_git(second, "https://example.com/owner/second.git")
    (first / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (second / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    first_graph = _analyze(first)
    second_graph = _analyze(second)
    first_snapshot = capture_repository_snapshot(first, first_graph)
    second_snapshot = capture_repository_snapshot(second, second_graph)

    with pytest.raises(ValueError, match="different repositories"):
        diff_snapshots(first_snapshot, first_graph, second_snapshot, second_graph)
