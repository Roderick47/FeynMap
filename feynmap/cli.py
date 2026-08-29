"""Command-line interface for the FeynMap semantic engine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .engine import FeynMapEngine
from .migration import MigrationPlanner
from .query import FeynMapQuery

COMMANDS = {"analyze", "query", "claim", "migrate-plan", "self-check", "snapshot", "diff", "legacy"}


def _write(payload: Dict[str, Any], output: Optional[str]) -> None:
    text = json.dumps(payload, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
        print(output)
    else:
        print(text)


def _language_help() -> str:
    return "Language selection. 'auto' analyzes all detected languages; comma-separated values such as python,javascript are supported."


def _framework_help() -> str:
    return "Framework selection. 'auto' applies all detected compatible frameworks; 'none' disables framework enrichment."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feynmap", description="Build a verifiable semantic model of software so humans and AI can reason about code without guessing.")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Build one unified repository semantic graph")
    analyze.add_argument("path", nargs="?", default=".")
    analyze.add_argument("--language", default="auto", help=_language_help())
    analyze.add_argument("--framework", default="auto", help=_framework_help())
    analyze.add_argument("--output", "-o", default="feynmap.semantic.json")

    query = sub.add_parser("query", help="Query dependencies, callers, impact, or an AI context bundle")
    query.add_argument("path")
    query.add_argument("symbol")
    query.add_argument("--kind", choices=["dependencies", "callers", "impact", "context"], default="context")
    query.add_argument("--depth", type=int, default=2)
    query.add_argument("--language", default="auto", help=_language_help())
    query.add_argument("--framework", default="auto", help=_framework_help())

    claim = sub.add_parser("claim", help="Fact-check a claimed code relationship")
    claim.add_argument("path")
    claim.add_argument("source")
    claim.add_argument("target")
    claim.add_argument("--relationship")
    claim.add_argument("--language", default="auto", help=_language_help())
    claim.add_argument("--framework", default="auto", help=_framework_help())

    migration = sub.add_parser("migrate-plan", help="Assess and partition a repository for migration")
    migration.add_argument("path")
    migration.add_argument("--to", default="rust")
    migration.add_argument("--max-unit-nodes", type=int, default=25)
    migration.add_argument("--language", default="auto", help=_language_help())
    migration.add_argument("--framework", default="auto", help=_framework_help())
    migration.add_argument("--output", "-o", default="feynmap.migration.json")

    self_check = sub.add_parser("self-check", help="Run the recursive FeynMap-on-FeynMap architecture benchmark")
    self_check.add_argument("path", nargs="?", default=".")
    self_check.add_argument("--golden", help="Optional golden architecture JSON; defaults to the packaged FeynMap golden model")
    self_check.add_argument("--language", default="auto", help=_language_help())
    self_check.add_argument("--framework", default="auto", help=_framework_help())
    self_check.add_argument("--output", "-o", default="feynmap.self-analysis.json")

    snapshot = sub.add_parser("snapshot", help="Analyze once and persist an immutable repository semantic snapshot")
    snapshot.add_argument("path", nargs="?", default=".")
    snapshot.add_argument("--store", help="SQLite snapshot store; defaults to <path>/.feynmap/snapshots.sqlite")
    snapshot.add_argument("--language", default="auto", help=_language_help())
    snapshot.add_argument("--framework", default="auto", help=_framework_help())

    snapshot_diff = sub.add_parser("diff", help="Compare two stored repository semantic snapshots without reparsing")
    snapshot_diff.add_argument("before", help="Before snapshot ID")
    snapshot_diff.add_argument("after", help="After snapshot ID")
    snapshot_diff.add_argument("--path", default=".", help="Repository checkout used to locate the default store")
    snapshot_diff.add_argument("--store", help="SQLite snapshot store; defaults to <path>/.feynmap/snapshots.sqlite")
    snapshot_diff.add_argument("--output", "-o")

    legacy = sub.add_parser("legacy", help="Run the V2 physics-notation pipeline")
    legacy.add_argument("path", nargs="?", default=".")
    legacy.add_argument("--framework", default="auto")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args_list = list(argv if argv is not None else sys.argv[1:])
    if not args_list:
        args_list = ["analyze", "."]
    elif args_list[0] not in COMMANDS and not args_list[0].startswith("-"):
        args_list.insert(0, "analyze")
    args = build_parser().parse_args(args_list)

    if args.command == "legacy":
        from pipeline import run_feynmap
        run_feynmap(args.path, framework=args.framework)
        return 0

    if args.command == "self-check":
        from .self_hosting import run_self_analysis
        _write(
            run_self_analysis(
                args.path,
                golden_path=args.golden,
                language=args.language,
                framework=args.framework,
            ),
            args.output,
        )
        return 0

    if args.command == "snapshot":
        from .snapshots import SnapshotStore, capture_and_store

        root = Path(args.path).resolve()
        graph = FeynMapEngine().analyze(str(root), language=args.language, framework=args.framework)
        store_path = Path(args.store).expanduser() if args.store else root / ".feynmap" / "snapshots.sqlite"
        store = SnapshotStore(store_path)
        persisted = capture_and_store(
            root,
            graph,
            store,
            analysis_options={"language_selection": args.language, "framework_selection": args.framework},
        )
        payload = persisted.to_dict(include_files=False)
        payload["store"] = str(store.path)
        payload["current"] = True
        _write(payload, None)
        return 0

    if args.command == "diff":
        from .diff import diff_store_snapshots
        from .snapshots import SnapshotStore

        root = Path(args.path).resolve()
        store_path = Path(args.store).expanduser() if args.store else root / ".feynmap" / "snapshots.sqlite"
        _write(diff_store_snapshots(SnapshotStore(store_path), args.before, args.after), args.output)
        return 0

    graph = FeynMapEngine().analyze(args.path, language=args.language, framework=args.framework)
    if args.command == "analyze":
        _write(graph.to_dict(), args.output)
    elif args.command == "query":
        api = FeynMapQuery(graph)
        payload = api.dependencies(args.symbol, args.depth) if args.kind == "dependencies" else api.callers(args.symbol, args.depth) if args.kind == "callers" else api.impact(args.symbol, args.depth) if args.kind == "impact" else api.context_bundle(args.symbol, args.depth)
        _write(payload, None)
    elif args.command == "claim":
        _write(FeynMapQuery(graph).validate_claim(args.source, args.target, args.relationship), None)
    elif args.command == "migrate-plan":
        _write(MigrationPlanner(graph).plan(target=args.to, max_nodes=args.max_unit_nodes), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
