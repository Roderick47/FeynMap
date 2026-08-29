from pathlib import Path

import pytest

from feynmap import FeynMapEngine
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


def test_snapshot_diff_reports_file_and_semantic_changes(tmp_path: Path):
    _fake_git(tmp_path)
    app = tmp_path / "app.py"
    app.write_text("def run():\n    return 1\n", encoding="utf-8")

    before_graph = _analyze(tmp_path)
    before_snapshot = capture_repository_snapshot(tmp_path, before_graph)
    store = SnapshotStore(tmp_path / ".feynmap" / "snapshots.sqlite")
    store.save(before_snapshot, before_graph)

    app.write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    after_graph = _analyze(tmp_path)
    after_snapshot = capture_repository_snapshot(tmp_path, after_graph)
    store.save(after_snapshot, after_graph)

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
