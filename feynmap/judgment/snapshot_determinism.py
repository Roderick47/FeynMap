"""Diagnose snapshot identity nondeterminism on frozen historical tasks."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..engine import FeynMapEngine
from ..snapshots import (
    _canonical_graph_identity_payload,
    capture_repository_snapshot,
)
from .context_ranker_v1f import _git_archive, _seed_snapshot_git_metadata


def _short(value: Any, limit: int = 240) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _diff(left: Any, right: Any, path: str = "$", limit: int = 40) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []

    def walk(a: Any, b: Any, current: str) -> None:
        if len(result) >= limit:
            return
        if type(a) is not type(b):
            result.append({"path": current, "left": _short(a), "right": _short(b)})
            return
        if isinstance(a, Mapping):
            keys = sorted(set(a) | set(b), key=str)
            for key in keys:
                if len(result) >= limit:
                    return
                child = "%s.%s" % (current, key)
                if key not in a:
                    result.append({"path": child, "left": "<missing>", "right": _short(b[key])})
                elif key not in b:
                    result.append({"path": child, "left": _short(a[key]), "right": "<missing>"})
                else:
                    walk(a[key], b[key], child)
            return
        if isinstance(a, list):
            if len(a) != len(b):
                result.append(
                    {
                        "path": current + ".length",
                        "left": str(len(a)),
                        "right": str(len(b)),
                    }
                )
            for index, (left_item, right_item) in enumerate(zip(a, b)):
                if len(result) >= limit:
                    return
                walk(left_item, right_item, "%s[%d]" % (current, index))
            return
        if a != b:
            result.append({"path": current, "left": _short(a), "right": _short(b)})

    walk(left, right, path)
    return result


def _run_once(
    repo: Path,
    repository_name: str,
    task: Mapping[str, Any],
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="feynmap-determinism-") as temp:
        extracted = Path(temp)
        revision = str(task["pre_fix_revision"])
        _git_archive(repo, revision, extracted)
        _seed_snapshot_git_metadata(extracted, repository_name, revision)
        graph = FeynMapEngine().analyze(str(extracted))
        snapshot = capture_repository_snapshot(
            extracted,
            graph,
            analysis_options={
                "experiment": "context_ranker_v1f",
                "source_revision": revision,
            },
        )
        return {
            "snapshot": snapshot,
            "graph_identity": _canonical_graph_identity_payload(graph.to_dict()),
        }


def run_diagnostic(
    repository_path: str,
    spec: Mapping[str, Any],
    task_id: str,
) -> Dict[str, Any]:
    repo = Path(repository_path).resolve()
    repository_name = str((spec.get("repository") or {}).get("name") or repo.name)
    task = next(
        (item for item in spec.get("tasks", []) if str(item.get("id")) == task_id),
        None,
    )
    if task is None:
        raise ValueError("unknown task id: %s" % task_id)

    first = _run_once(repo, repository_name, task)
    second = _run_once(repo, repository_name, task)
    left = first["snapshot"]
    right = second["snapshot"]

    component_match = {
        "repository_key": left.repository_key == right.repository_key,
        "revision": left.revision == right.revision,
        "content_hash": left.content_hash == right.content_hash,
        "graph_hash": left.graph_hash == right.graph_hash,
        "analysis_options": left.analysis_options == right.analysis_options,
        "snapshot_id": left.snapshot_id == right.snapshot_id,
    }
    differences: List[Dict[str, str]] = []
    if not component_match["graph_hash"]:
        differences = _diff(first["graph_identity"], second["graph_identity"])

    return {
        "task": task_id,
        "revision": str(task["pre_fix_revision"]),
        "component_match": component_match,
        "first": {
            "snapshot_id": left.snapshot_id,
            "repository_key": left.repository_key,
            "revision": left.revision,
            "content_hash": left.content_hash,
            "graph_hash": left.graph_hash,
            "analysis_options": left.analysis_options,
        },
        "second": {
            "snapshot_id": right.snapshot_id,
            "repository_key": right.repository_key,
            "revision": right.revision,
            "content_hash": right.content_hash,
            "graph_hash": right.graph_hash,
            "analysis_options": right.analysis_options,
        },
        "graph_identity_differences": differences,
        "difference_limit": 40,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the same historical FeynMap analysis twice and diff snapshot identity"
    )
    parser.add_argument("repository")
    parser.add_argument("--spec", default="experiments/context_ranker_v1f.json")
    parser.add_argument("--task", required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    result = run_diagnostic(args.repository, spec, args.task)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
