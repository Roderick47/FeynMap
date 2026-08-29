from pathlib import Path

from feynmap import ContextBudget, FeynMapEngine, StoredSnapshotContext, estimate_tokens
from feynmap.snapshots import SnapshotStore, capture_repository_snapshot


def _fake_git(root: Path) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = https://example.com/owner/context.git\n',
        encoding="utf-8",
    )


def _stored_project(root: Path):
    _fake_git(root)
    (root / "app.py").write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    graph = FeynMapEngine().analyze(str(root), language="python", framework="none")
    snapshot = capture_repository_snapshot(
        root,
        graph,
        analysis_options={"language_selection": "python", "framework_selection": "none"},
    )
    store = SnapshotStore(root / ".feynmap" / "snapshots.sqlite")
    store.save(snapshot, graph)
    return snapshot, graph, store


def test_stored_context_loads_without_repository_reparse(tmp_path: Path):
    snapshot, graph, store = _stored_project(tmp_path)

    context = StoredSnapshotContext.load(store, snapshot.snapshot_id)
    summary = context.repository_summary()
    symbol = context.symbol("app.run")

    assert summary["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert summary["graph"]["node_count"] == len(graph.nodes)
    assert summary["graph"]["analysis_contract_version"] == "1.0.0"
    assert symbol["symbol"]["qualified_name"] == "app.run"
    assert any(edge["kind"] == "calls" for edge in symbol["outgoing"])


def test_context_bundle_is_evidence_preserving_and_budgeted(tmp_path: Path):
    snapshot, graph, store = _stored_project(tmp_path)
    context = StoredSnapshotContext.load(store, snapshot.snapshot_id)

    bundle = context.context_bundle(
        "app.run",
        depth=2,
        budget=ContextBudget(max_tokens=700, max_nodes=10, max_edges=20),
    )

    assert bundle["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert bundle["root"]["qualified_name"] == "app.run"
    assert bundle["grounding"]["unknown"]
    assert bundle["budget"]["requested_max_tokens"] == 700
    assert bundle["budget"]["max_tokens"] == 700
    assert bundle["budget"]["estimated_tokens"] <= 700
    assert bundle["budget"]["included_nodes"] >= 1
    assert any(item["relationship"] == "calls" for item in bundle["relationships"])


def test_context_budget_has_explicit_minimum_and_truncates_deterministically(tmp_path: Path):
    snapshot, graph, store = _stored_project(tmp_path)
    context = StoredSnapshotContext.load(store, snapshot.snapshot_id)

    requested = ContextBudget(max_tokens=128, max_nodes=1, max_edges=1)
    first = context.context_bundle("app.run", depth=4, budget=requested)
    second = context.context_bundle("app.run", depth=4, budget=requested)

    assert first == second
    assert first["budget"]["requested_max_tokens"] == 128
    assert first["budget"]["minimum_supported_tokens"] == 512
    assert first["budget"]["max_tokens"] == 512
    assert first["budget"]["truncated"] is True
    assert first["budget"]["included_nodes"] <= 2
    assert first["budget"]["included_relationships"] <= 1
    assert first["budget"]["estimated_tokens"] <= first["budget"]["max_tokens"]


def test_unresolved_payload_preserves_unknown_semantics(tmp_path: Path):
    snapshot, graph, store = _stored_project(tmp_path)
    context = StoredSnapshotContext.load(store, snapshot.snapshot_id)

    unresolved = context.unresolved()

    assert unresolved["snapshot_id"] == snapshot.snapshot_id
    assert "python_unresolved_calls" in unresolved
    assert "integration_unresolved_contracts" in unresolved


def test_token_estimator_is_transport_neutral_and_deterministic():
    payload = {"b": 2, "a": "hello"}
    assert estimate_tokens(payload) == estimate_tokens({"a": "hello", "b": 2})
    assert estimate_tokens(payload) > 0
