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

COMMANDS = {"analyze", "query", "claim", "migrate-plan", "legacy"}


def _write(payload: Dict[str, Any], output: Optional[str]) -> None:
    text = json.dumps(payload, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
        print(output)
    else:
        print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feynmap", description="Build a verifiable semantic model of software so humans and AI can reason about code without guessing.")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Build the canonical semantic graph")
    analyze.add_argument("path", nargs="?", default=".")
    analyze.add_argument("--language", default="auto")
    analyze.add_argument("--framework", default="auto")
    analyze.add_argument("--output", "-o", default="feynmap.semantic.json")

    query = sub.add_parser("query", help="Query dependencies, callers, impact, or an AI context bundle")
    query.add_argument("path")
    query.add_argument("symbol")
    query.add_argument("--kind", choices=["dependencies", "callers", "impact", "context"], default="context")
    query.add_argument("--depth", type=int, default=2)
    query.add_argument("--language", default="auto")
    query.add_argument("--framework", default="auto")

    claim = sub.add_parser("claim", help="Fact-check a claimed code relationship")
    claim.add_argument("path")
    claim.add_argument("source")
    claim.add_argument("target")
    claim.add_argument("--relationship")
    claim.add_argument("--language", default="auto")
    claim.add_argument("--framework", default="auto")

    migration = sub.add_parser("migrate-plan", help="Assess and partition a repository for migration")
    migration.add_argument("path")
    migration.add_argument("--to", default="rust")
    migration.add_argument("--max-unit-nodes", type=int, default=25)
    migration.add_argument("--language", default="auto")
    migration.add_argument("--framework", default="auto")
    migration.add_argument("--output", "-o", default="feynmap.migration.json")

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
