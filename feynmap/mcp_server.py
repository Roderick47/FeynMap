"""Optional local MCP transport for FeynMap's stored grounding service.

The semantic core remains Python 3.8 compatible. This module imports the official
MCP SDK lazily and is only usable on Python 3.10+ with the ``feynmap[mcp]`` extra
installed. MCP tool calls never trigger repository analysis; they query one
already-persisted immutable semantic snapshot through ``GroundingService``.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from .grounding import GroundingService
from .snapshots import SnapshotStore, repository_locator

MCP_COMPONENT_MIN_PYTHON: Tuple[int, int] = (3, 10)
MCP_COMPONENT_NAME = "feynmap-mcp"


def mcp_runtime_supported() -> bool:
    return sys.version_info[:2] >= MCP_COMPONENT_MIN_PYTHON


def _require_mcp_sdk():
    if not mcp_runtime_supported():
        raise RuntimeError(
            "FeynMap core supports Python 3.8+, but the optional MCP component "
            "requires Python 3.10+. Run feynmap-mcp with Python 3.10 or newer."
        )
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError(
            "The optional MCP SDK is not installed. Install FeynMap with "
            "`pip install 'feynmap[mcp]'` (Python 3.10+)."
        ) from exc
    return MCPServer, ToolAnnotations


def repository_key_for_path(project_path: Path) -> str:
    locator = repository_locator(project_path.resolve())
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()


def default_store_path(project_path: Path) -> Path:
    return project_path.resolve() / ".feynmap" / "snapshots.sqlite"


def resolve_grounding_service(
    store: SnapshotStore,
    project_path: Path,
    snapshot_id: Optional[str] = None,
    repository_key: Optional[str] = None,
) -> GroundingService:
    if snapshot_id:
        return GroundingService(store, snapshot_id)

    key = repository_key or repository_key_for_path(project_path)
    current = store.current_snapshot_id(key)
    if not current:
        raise KeyError(
            "No current FeynMap snapshot exists for repository %s. "
            "Run `feynmap snapshot %s` first or pass --snapshot/--repository-key."
            % (key, project_path.resolve())
        )
    return GroundingService(store, current)


def build_mcp_server(
    store_path: Path,
    project_path: Path = Path("."),
    snapshot_id: Optional[str] = None,
    repository_key: Optional[str] = None,
):
    """Build a read-only MCPServer over one stored FeynMap snapshot."""
    MCPServer, ToolAnnotations = _require_mcp_sdk()
    store = SnapshotStore(store_path)
    service = resolve_grounding_service(
        store,
        project_path=project_path,
        snapshot_id=snapshot_id,
        repository_key=repository_key,
    )

    mcp = MCPServer("FeynMap")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @mcp.tool(
        name="repository_summary",
        description="Return repository identity, languages, frameworks, diagnostics, evidence coverage, and semantic graph size from the selected immutable FeynMap snapshot.",
        annotations=read_only,
    )
    def repository_summary() -> Dict[str, Any]:
        return service.call("repository_summary")

    @mcp.tool(
        name="get_symbol",
        description="Return one grounded semantic symbol plus its direct incoming and outgoing relationships with evidence.",
        annotations=read_only,
    )
    def get_symbol(symbol: str) -> Dict[str, Any]:
        return service.call("get_symbol", {"symbol": symbol})

    @mcp.tool(
        name="find_callers",
        description="Walk evidenced caller relationships from a symbol in the selected stored graph.",
        annotations=read_only,
    )
    def find_callers(symbol: str, depth: int = 2) -> Dict[str, Any]:
        return service.call("find_callers", {"symbol": symbol, "depth": depth})

    @mcp.tool(
        name="find_dependencies",
        description="Walk evidenced outgoing dependency relationships from a symbol in the selected stored graph.",
        annotations=read_only,
    )
    def find_dependencies(symbol: str, depth: int = 2) -> Dict[str, Any]:
        return service.call("find_dependencies", {"symbol": symbol, "depth": depth})

    @mcp.tool(
        name="change_impact",
        description="Return the evidenced caller/impact closure for a symbol from the stored semantic graph.",
        annotations=read_only,
    )
    def change_impact(symbol: str, depth: int = 4) -> Dict[str, Any]:
        return service.call("change_impact", {"symbol": symbol, "depth": depth})

    @mcp.tool(
        name="validate_claim",
        description="Check whether the selected snapshot contains evidence for a claimed source-to-target relationship. Missing evidence remains unknown rather than false.",
        annotations=read_only,
    )
    def validate_claim(
        source: str,
        target: str,
        relationship: Optional[str] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {"source": source, "target": target}
        if relationship is not None:
            arguments["relationship"] = relationship
        return service.call("validate_claim", arguments)

    @mcp.tool(
        name="trace_path",
        description="Find one evidenced semantic graph path between two symbols. No returned path means no current evidence within the requested boundary, not impossibility.",
        annotations=read_only,
    )
    def trace_path(
        source: str,
        target: str,
        max_depth: int = 6,
        direction: str = "outgoing",
    ) -> Dict[str, Any]:
        return service.call(
            "trace_path",
            {
                "source": source,
                "target": target,
                "max_depth": max_depth,
                "direction": direction,
            },
        )

    @mcp.tool(
        name="find_integrations",
        description="Return evidenced cross-language, framework, process, data, or other integration relationships, optionally scoped to a symbol.",
        annotations=read_only,
    )
    def find_integrations(
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {"limit": limit}
        if symbol is not None:
            arguments["symbol"] = symbol
        return service.call("find_integrations", arguments)

    @mcp.tool(
        name="explain_evidence",
        description="Explain the provenance and confidence attached to a symbol and its direct semantic relationships.",
        annotations=read_only,
    )
    def explain_evidence(symbol: str) -> Dict[str, Any]:
        return service.call("explain_evidence", {"symbol": symbol})

    @mcp.tool(
        name="unresolved",
        description="Return unresolved calls and integration contracts so the client can preserve uncertainty instead of guessing.",
        annotations=read_only,
    )
    def unresolved(limit: int = 100) -> Dict[str, Any]:
        return service.call("unresolved", {"limit": limit})

    @mcp.tool(
        name="context_bundle",
        description="Return a deterministic evidence-preserving semantic neighborhood around a symbol under an approximate token budget.",
        annotations=read_only,
    )
    def context_bundle(
        symbol: str,
        depth: int = 2,
        max_tokens: int = 4000,
        max_nodes: int = 80,
        max_edges: int = 120,
    ) -> Dict[str, Any]:
        return service.call(
            "context_bundle",
            {
                "symbol": symbol,
                "depth": depth,
                "max_tokens": max_tokens,
                "max_nodes": max_nodes,
                "max_edges": max_edges,
            },
        )

    @mcp.tool(
        name="semantic_diff",
        description="Compare two immutable snapshots of the same repository and return file plus semantic changes without reparsing source.",
        annotations=read_only,
    )
    def semantic_diff(
        before_snapshot: str,
        after_snapshot: str,
    ) -> Dict[str, Any]:
        return service.call(
            "semantic_diff",
            {
                "before_snapshot": before_snapshot,
                "after_snapshot": after_snapshot,
            },
        )

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=MCP_COMPONENT_NAME,
        description="Serve an existing FeynMap semantic snapshot over local MCP stdio.",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Repository checkout used to locate the default snapshot store/current repository identity.",
    )
    parser.add_argument(
        "--store",
        help="SQLite snapshot store. Defaults to <project>/.feynmap/snapshots.sqlite.",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--snapshot",
        help="Pin the MCP process to one immutable snapshot ID.",
    )
    selection.add_argument(
        "--repository-key",
        help="Serve the current snapshot pointer for an explicit repository key.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    project = Path(args.project).expanduser().resolve()
    store_path = Path(args.store).expanduser().resolve() if args.store else default_store_path(project)
    try:
        server = build_mcp_server(
            store_path=store_path,
            project_path=project,
            snapshot_id=args.snapshot,
            repository_key=args.repository_key,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        print("feynmap-mcp: %s" % exc, file=sys.stderr)
        return 2

    # stdio is the official SDK's default local transport. Never print to stdout:
    # stdout is the MCP JSON-RPC wire.
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
