from pathlib import Path

from feynmap import FeynMapEngine
from feynmap.incremental import analyze_incrementally, incremental_snapshot, plan_incremental_analysis
from feynmap.snapshots import SnapshotStore, capture_repository_snapshot


def _fake_git(root: Path) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = https://example.com/owner/repo.git\n',
        encoding="utf-8",
    )


def _project(root: Path) -> None:
    _fake_git(root)
    (root / "lib.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "app.py").write_text(
        "from lib import helper\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )


def _baseline(root: Path):
    graph = FeynMapEngine().analyze(str(root), language="python", framework="none")
    snapshot = capture_repository_snapshot(
        root,
        graph,
        analysis_options={"language_selection": "python", "framework_selection": "none"},
    )
    return snapshot, graph


class _FailIfCalled:
    def analyze(self, *args, **kwargs):
        raise AssertionError("full analysis should not run for unchanged inventory")


class _RecordingEngine:
    def __init__(self):
        self.called = False

    def analyze(self, project_path, language="auto", framework="auto"):
        self.called = True
        return FeynMapEngine().analyze(project_path, language=language, framework=framework)


def test_unchanged_repository_reuses_stored_graph_without_analysis(tmp_path: Path):
    _project(tmp_path)
    snapshot, graph = _baseline(tmp_path)

    reused, plan = analyze_incrementally(
        tmp_path,
        snapshot,
        graph,
        language="python",
        framework="none",
        engine=_FailIfCalled(),
    )

    assert reused is graph
    assert plan.mode == "reuse"
    assert plan.fallback is False
    assert plan.changed_files == []
    assert sorted(plan.reused_files) == ["app.py", "lib.py"]


def test_modified_dependency_computes_conservative_closure_then_full_rebuilds(tmp_path: Path):
    _project(tmp_path)
    snapshot, graph = _baseline(tmp_path)
    (tmp_path / "lib.py").write_text("def helper():\n    return 2\n", encoding="utf-8")

    plan = plan_incremental_analysis(
        tmp_path,
        snapshot,
        graph,
        analysis_options={"language_selection": "python", "framework_selection": "none"},
    )

    assert plan.mode == "partial_candidate"
    assert plan.fallback is True
    assert plan.changed_files == ["lib.py"]
    assert "lib.py" in plan.impacted_files
    assert "app.py" in plan.impacted_files

    engine = _RecordingEngine()
    refreshed, actual_plan = analyze_incrementally(
        tmp_path,
        snapshot,
        graph,
        language="python",
        framework="none",
        engine=engine,
    )
    assert engine.called is True
    assert actual_plan.mode == "partial_candidate"
    assert any(node.qualified_name == "lib.helper" for node in refreshed.nodes)


def test_added_file_forces_topology_rebuild(tmp_path: Path):
    _project(tmp_path)
    snapshot, graph = _baseline(tmp_path)
    (tmp_path / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")

    plan = plan_incremental_analysis(
        tmp_path,
        snapshot,
        graph,
        analysis_options={"language_selection": "python", "framework_selection": "none"},
    )

    assert plan.mode == "full_rebuild"
    assert plan.fallback is True
    assert "extra.py" in plan.changed_files


def test_changed_analysis_options_forbid_reuse(tmp_path: Path):
    _project(tmp_path)
    snapshot, graph = _baseline(tmp_path)

    plan = plan_incremental_analysis(
        tmp_path,
        snapshot,
        graph,
        analysis_options={"language_selection": "auto", "framework_selection": "auto"},
    )

    assert plan.mode == "full_rebuild"
    assert "analysis options" in plan.reason


def test_incremental_snapshot_updates_current_pointer(tmp_path: Path):
    _project(tmp_path)
    snapshot, graph = _baseline(tmp_path)
    store = SnapshotStore(tmp_path / ".feynmap" / "snapshots.sqlite")
    store.save(snapshot, graph)

    next_snapshot, next_graph, plan = incremental_snapshot(
        tmp_path,
        store,
        snapshot.snapshot_id,
        language="python",
        framework="none",
    )

    assert plan.mode == "reuse"
    assert next_snapshot.snapshot_id == snapshot.snapshot_id
    assert next_graph.to_dict() == graph.to_dict()
    assert store.current_snapshot_id(snapshot.repository_key) == snapshot.snapshot_id
