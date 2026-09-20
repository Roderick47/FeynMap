import asyncio
import sys
from pathlib import Path

import pytest

from feynmap import FeynMapEngine
from feynmap.mcp_server import (
    default_store_path,
    mcp_runtime_supported,
    repository_key_for_path,
    resolve_grounding_service,
)
from feynmap.snapshots import SnapshotStore, capture_repository_snapshot


def _fake_git(root: Path) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = https://example.com/owner/mcp-demo.git\n',
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
    store = SnapshotStore(default_store_path(root))
    store.save(snapshot, graph, set_current=True)
    return snapshot, graph, store


def test_optional_mcp_module_imports_without_sdk_or_runtime_upgrade(tmp_path: Path):
    assert default_store_path(tmp_path) == tmp_path.resolve() / ".feynmap" / "snapshots.sqlite"
    assert isinstance(mcp_runtime_supported(), bool)


def test_repository_key_matches_snapshot_identity(tmp_path: Path):
    snapshot, _, _ = _stored_project(tmp_path)
    assert repository_key_for_path(tmp_path) == snapshot.repository_key


def test_grounding_service_defaults_to_current_snapshot(tmp_path: Path):
    snapshot, _, store = _stored_project(tmp_path)
    service = resolve_grounding_service(store, project_path=tmp_path)
    assert service.snapshot.snapshot_id == snapshot.snapshot_id


def test_explicit_snapshot_pins_service(tmp_path: Path):
    snapshot, _, store = _stored_project(tmp_path)
    service = resolve_grounding_service(
        store,
        project_path=tmp_path,
        snapshot_id=snapshot.snapshot_id,
    )
    assert service.snapshot.snapshot_id == snapshot.snapshot_id


def test_missing_current_snapshot_is_explicit(tmp_path: Path):
    _fake_git(tmp_path)
    store = SnapshotStore(default_store_path(tmp_path))
    with pytest.raises(KeyError, match="No current FeynMap snapshot"):
        resolve_grounding_service(store, project_path=tmp_path)


def test_mcp_protocol_lists_and_calls_grounding_tools(tmp_path: Path):
    pytest.importorskip("mcp")
    if not mcp_runtime_supported():
        pytest.skip("official MCP SDK requires Python 3.10+")

    from mcp import Client
    from feynmap.mcp_server import build_mcp_server

    snapshot, _, store = _stored_project(tmp_path)
    server = build_mcp_server(
        store_path=store.path,
        project_path=tmp_path,
        snapshot_id=snapshot.snapshot_id,
    )

    async def exercise() -> None:
        async with Client(server) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {
                "repository_summary",
                "get_symbol",
                "find_callers",
                "find_dependencies",
                "change_impact",
                "validate_claim",
                "trace_path",
                "find_integrations",
                "explain_evidence",
                "unresolved",
                "context_bundle",
                "semantic_diff",
            }.issubset(names)

            summary = await client.call_tool("repository_summary", {})
            assert summary.is_error is False
            assert summary.structured_content is not None
            assert summary.structured_content["snapshot"]["snapshot_id"] == snapshot.snapshot_id

            symbol = await client.call_tool("get_symbol", {"symbol": "app.run"})
            assert symbol.is_error is False
            assert symbol.structured_content["symbol"]["qualified_name"] == "app.run"

            claim = await client.call_tool(
                "validate_claim",
                {"source": "app.run", "target": "app.helper", "relationship": "calls"},
            )
            assert claim.is_error is False
            assert claim.structured_content["supported"] is True

            bundle = await client.call_tool(
                "context_bundle",
                {"symbol": "app.run", "depth": 2, "max_tokens": 900},
            )
            assert bundle.is_error is False
            assert bundle.structured_content["root"]["qualified_name"] == "app.run"
            assert bundle.structured_content["budget"]["estimated_tokens"] <= bundle.structured_content["budget"]["max_tokens"]

    asyncio.run(exercise())


def test_stdio_subprocess_serves_snapshot_without_network(tmp_path: Path):
    pytest.importorskip("mcp")
    if not mcp_runtime_supported():
        pytest.skip("official MCP SDK requires Python 3.10+")

    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    snapshot, _, store = _stored_project(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "feynmap.mcp_server",
            "--project",
            str(tmp_path),
            "--store",
            str(store.path),
            "--snapshot",
            snapshot.snapshot_id,
        ],
        env={"PYTHONPATH": str(repo_root)},
        cwd=str(tmp_path),
    )

    async def exercise() -> None:
        async with Client(stdio_client(params)) as client:
            listed = await client.list_tools()
            assert "get_symbol" in {tool.name for tool in listed.tools}
            result = await client.call_tool("get_symbol", {"symbol": "app.run"})
            assert result.is_error is False
            assert result.structured_content["snapshot_id"] == snapshot.snapshot_id
            assert result.structured_content["symbol"]["qualified_name"] == "app.run"

    asyncio.run(exercise())
