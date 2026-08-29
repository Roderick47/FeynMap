from pathlib import Path

from feynmap import FeynMapEngine, GROUNDING_TOOLS, GroundingService
from feynmap.snapshots import SnapshotStore, capture_repository_snapshot


def _fake_git(root: Path) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = https://example.com/owner/grounding.git\n',
        encoding="utf-8",
    )


def _service(root: Path):
    _fake_git(root)
    (root / "lib.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "app.py").write_text(
        "from lib import helper\n\n"
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
    return GroundingService(store, snapshot.snapshot_id), snapshot, store


def test_tool_catalog_is_deterministic_json_schema_contract():
    catalog = GroundingService.tool_catalog()

    assert [item["name"] for item in catalog] == [tool.name for tool in GROUNDING_TOOLS]
    assert catalog[0]["contract_version"] == "1.0.0"
    assert all(item["read_only"] is True for item in catalog)
    assert all(item["input_schema"]["$schema"].endswith("2020-12/schema") for item in catalog)
    assert "context_bundle" in {item["name"] for item in catalog}
    assert "semantic_diff" in {item["name"] for item in catalog}


def test_service_dispatches_stored_snapshot_queries(tmp_path: Path):
    service, snapshot, _ = _service(tmp_path)

    summary = service.call("repository_summary")
    symbol = service.call("get_symbol", {"symbol": "app.run"})
    dependencies = service.call("find_dependencies", {"symbol": "app.run", "depth": 2})
    callers = service.call("find_callers", {"symbol": "lib.helper", "depth": 2})
    claim = service.call(
        "validate_claim",
        {"source": "app.run", "target": "lib.helper", "relationship": "calls"},
    )

    assert summary["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert symbol["symbol"]["qualified_name"] == "app.run"
    assert dependencies["snapshot_id"] == snapshot.snapshot_id
    assert callers["snapshot_id"] == snapshot.snapshot_id
    assert claim["snapshot_id"] == snapshot.snapshot_id
    assert claim["supported"] is True


def test_trace_path_returns_evidenced_path_or_explicit_unknown(tmp_path: Path):
    service, snapshot, _ = _service(tmp_path)

    found = service.call(
        "trace_path",
        {"source": "app.run", "target": "lib.helper", "max_depth": 3},
    )
    missing = service.call(
        "trace_path",
        {"source": "lib.helper", "target": "app.run", "max_depth": 3, "direction": "outgoing"},
    )

    assert found["snapshot_id"] == snapshot.snapshot_id
    assert found["found"] is True
    assert any(edge["kind"] == "calls" for edge in found["path"]["relationships"])
    assert missing["found"] is False
    assert missing["status"] == "unknown"
    assert "does not prove" in missing["note"]


def test_context_and_evidence_tools_preserve_grounding(tmp_path: Path):
    service, snapshot, _ = _service(tmp_path)

    context = service.call(
        "context_bundle",
        {"symbol": "app.run", "depth": 2, "max_tokens": 1200},
    )
    evidence = service.call("explain_evidence", {"symbol": "app.run"})
    unresolved = service.call("unresolved", {"limit": 20})

    assert context["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert context["budget"]["estimated_tokens"] <= context["budget"]["max_tokens"]
    assert evidence["snapshot_id"] == snapshot.snapshot_id
    assert evidence["grounding"]["unknown"]
    assert unresolved["snapshot_id"] == snapshot.snapshot_id


def test_semantic_diff_tool_compares_stored_snapshots(tmp_path: Path):
    service, first_snapshot, store = _service(tmp_path)

    (tmp_path / "lib.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    second_graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")
    second_snapshot = capture_repository_snapshot(
        tmp_path,
        second_graph,
        analysis_options={"language_selection": "python", "framework_selection": "none"},
    )
    store.save(second_snapshot, second_graph)

    delta = service.call(
        "semantic_diff",
        {
            "before_snapshot": first_snapshot.snapshot_id,
            "after_snapshot": second_snapshot.snapshot_id,
        },
    )

    assert delta["before_snapshot_id"] == first_snapshot.snapshot_id
    assert delta["after_snapshot_id"] == second_snapshot.snapshot_id
    assert delta["content_changed"] is True


def test_current_snapshot_constructor_uses_store_pointer(tmp_path: Path):
    service, snapshot, store = _service(tmp_path)

    current = GroundingService.from_current(store, snapshot.repository_key)

    assert current.snapshot.snapshot_id == service.snapshot.snapshot_id
