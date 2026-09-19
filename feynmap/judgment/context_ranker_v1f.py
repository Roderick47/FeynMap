"""Context Ranker v1F: historical change localization on unseen application code.

v1F intentionally freezes the v1E direct, naive, adaptive-frontier, and Jev
ranking behavior. The experiment changes only the evaluation domain: each task
is run against a historical repository revision from before a real fix, then
scored against production files changed by the later patch.

Files introduced by the fix are reported as novel targets and are not counted
as retrieval failures because they did not exist in the pre-fix repository.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import subprocess
import tarfile
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..context import StoredSnapshotContext, estimate_tokens
from ..engine import FeynMapEngine
from ..snapshots import capture_repository_snapshot
from .context_ranker_v1e import (
    _adaptive_selection,
    _direct_selection,
    _naive_selection,
    _node_label,
    _selection_bundle,
    build_frontier_state,
    rerank_frontier,
)
from .jev import JevJudgmentProvider
from .ranking import RankedCandidate, baseline_rank
from .real_benchmark import _average

V1F_SCHEMA = "feynmap.context_ranker_v1f.v1"


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _node_path(node: Any) -> Optional[str]:
    location = getattr(node, "location", None)
    path = getattr(location, "path", None) if location is not None else None
    return _normalize_path(path) if path else None


def _candidate_path(candidate: Mapping[str, Any]) -> Optional[str]:
    location = candidate.get("location")
    if isinstance(location, Mapping) and location.get("path"):
        return _normalize_path(str(location["path"]))
    return None


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("schema") != V1F_SCHEMA:
        raise ValueError("unsupported Context Ranker v1F schema")
    retrieval = spec.get("retrieval") or {}
    if int(retrieval.get("max_depth", 0)) < 2:
        raise ValueError("v1F retrieval.max_depth must be at least 2")
    for key in ("direct_max_candidates", "adaptive_max_candidates", "naive_max_candidates"):
        if int(retrieval.get(key, 0)) <= 0:
            raise ValueError("v1F requires retrieval.%s" % key)
    adaptive = spec.get("adaptive") or {}
    if int(adaptive.get("max_branch_expansions_per_depth", 0)) <= 0:
        raise ValueError("v1F requires adaptive.max_branch_expansions_per_depth")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v1F requires tasks")
    seen = set()
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("each v1F task must be an object")
        for key in ("id", "source_pr", "pre_fix_revision", "root", "description", "gold_changed_files"):
            if not task.get(key):
                raise ValueError("each v1F task requires %s" % key)
        task_id = str(task["id"])
        if task_id in seen:
            raise ValueError("duplicate v1F task id: %s" % task_id)
        seen.add(task_id)
        description = str(task["description"]).casefold()
        for path in task["gold_changed_files"]:
            normalized = _normalize_path(str(path))
            if normalized.casefold() in description:
                raise ValueError("task description leaks gold file path: %s" % normalized)


def _git_archive(repo_path: Path, revision: str, destination: Path) -> None:
    command = ["git", "-C", str(repo_path), "archive", "--format=tar", revision]
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError("git archive failed for %s: %s" % (revision, message))
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(process.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                raise ValueError("unsafe path in git archive: %s" % member.name)
        archive.extractall(destination)


def _seed_snapshot_git_metadata(
    destination: Path,
    repository_name: str,
    revision: str,
) -> None:
    """Give an archived revision deterministic repository identity metadata."""
    git_dir = destination / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(str(revision).strip() + "\n", encoding="utf-8")
    origin = "https://github.com/%s.git" % str(repository_name).strip().strip("/")
    (git_dir / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n'
        '[remote "origin"]\n\turl = %s\n' % origin,
        encoding="utf-8",
    )


def _gold_files(
    context: StoredSnapshotContext,
    task: Mapping[str, Any],
) -> Tuple[Set[str], Set[str]]:
    inventory = {_normalize_path(item.path) for item in context.snapshot.files}
    requested = {_normalize_path(str(path)) for path in task["gold_changed_files"]}
    return requested & inventory, requested - inventory


def _ranked_file_order(
    root: Any,
    ranked: Sequence[RankedCandidate],
) -> List[str]:
    order: List[str] = []
    seen: Set[str] = set()
    root_path = _node_path(root)
    if root_path:
        order.append(root_path)
        seen.add(root_path)
    for item in ranked:
        path = _candidate_path(item.candidate)
        if not path or path in seen:
            continue
        seen.add(path)
        order.append(path)
    return order


def _dcg(relevances: Sequence[int]) -> float:
    total = 0.0
    for index, relevance in enumerate(relevances):
        if relevance:
            total += float(relevance) / math.log2(index + 2.0)
    return total


def _file_metrics(
    order: Sequence[str],
    gold: Set[str],
    *,
    ks: Sequence[int],
    path_backed_files: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    unique_order = list(dict.fromkeys(_normalize_path(item) for item in order if item))
    gold = {_normalize_path(item) for item in gold}
    positions = {
        path: index + 1
        for index, path in enumerate(unique_order)
        if path in gold
    }
    payload: Dict[str, Any] = {
        "file_count": len(unique_order),
        "gold_file_count": len(gold),
        "missing_gold_files": sorted(gold - set(unique_order)),
        "reciprocal_rank": (1.0 / min(positions.values())) if positions else 0.0,
    }
    precisions: List[float] = []
    hits = 0
    for index, path in enumerate(unique_order, 1):
        if path in gold:
            hits += 1
            precisions.append(hits / float(index))
    payload["average_precision"] = (
        sum(precisions) / len(gold) if gold else None
    )
    full_k = max(positions.values()) if gold and len(positions) == len(gold) else None
    payload["full_recall_min_k"] = full_k
    payload["context_file_ratio"] = (
        full_k / float(len(unique_order))
        if full_k is not None and unique_order
        else None
    )

    ideal = [1] * len(gold)
    path_backed = path_backed_files or set()
    for k in ks:
        prefix = unique_order[: int(k)]
        relevant = sum(1 for path in prefix if path in gold)
        denom = min(int(k), len(unique_order))
        payload["precision@%d" % k] = relevant / float(denom) if denom else 0.0
        payload["recall@%d" % k] = relevant / float(len(gold)) if gold else None
        payload["noise@%d" % k] = 1.0 - payload["precision@%d" % k] if denom else 0.0
        actual_dcg = _dcg([1 if path in gold else 0 for path in prefix])
        ideal_dcg = _dcg(ideal[: int(k)])
        payload["ndcg@%d" % k] = actual_dcg / ideal_dcg if ideal_dcg else None
        if gold:
            payload["path_recall@%d" % k] = (
                sum(1 for path in prefix if path in gold and path in path_backed)
                / float(len(gold))
            )
        else:
            payload["path_recall@%d" % k] = None
    return payload


def _path_backing(
    context: StoredSnapshotContext,
    root: Any,
    selection: Mapping[str, Any],
    gold_files: Set[str],
) -> Tuple[Set[str], Dict[str, int]]:
    selected = {root.id} | set(selection.get("candidate_ids") or [])
    adjacency: Dict[str, List[str]] = {}
    for edge in selection.get("edges") or []:
        if edge.source in selected and edge.target in selected:
            adjacency.setdefault(edge.source, []).append(edge.target)

    distances = {root.id: 0}
    queue = deque([root.id])
    while queue:
        source = queue.popleft()
        for target in adjacency.get(source, []):
            if target in distances:
                continue
            distances[target] = distances[source] + 1
            queue.append(target)

    path_backed: Set[str] = set()
    lengths: Dict[str, int] = {}
    for node_id in selected:
        if node_id not in distances:
            continue
        node = context.graph.node(node_id)
        path = _node_path(node) if node is not None else None
        if not path or path not in gold_files:
            continue
        path_backed.add(path)
        current = lengths.get(path)
        if current is None or distances[node_id] < current:
            lengths[path] = distances[node_id]
    return path_backed, lengths


def _row(
    context: StoredSnapshotContext,
    root: Any,
    selection: Mapping[str, Any],
    gold_existing: Set[str],
    description: str,
    *,
    ks: Sequence[int],
    provider=None,
) -> Dict[str, Any]:
    bundle = _selection_bundle(
        context,
        root,
        selection["candidate_ids"],
        selection["edges"],
        selection["provenance"],
    )
    candidates = list(bundle["nodes"])
    baseline = baseline_rank(candidates)
    path_backed, path_lengths = _path_backing(
        context, root, selection, gold_existing
    )
    baseline_files = _ranked_file_order(root, baseline)
    row: Dict[str, Any] = {
        "candidate_count": len(candidates),
        "candidate_tokens": estimate_tokens(candidates),
        "context_file_count": len(baseline_files),
        "compact_path_state_tokens": estimate_tokens(
            build_frontier_state({"description": description}, bundle, candidates)
        ),
        "max_depth_reached": selection.get("max_depth_reached"),
        "expansion_count": selection.get("expansion_count"),
        "declared_complete": bool(selection.get("declared_complete")),
        "stopped_reason": selection.get("stopped_reason"),
        "baseline_file_order": baseline_files,
        "baseline": _file_metrics(
            baseline_files, gold_existing, ks=ks, path_backed_files=path_backed
        ),
        "path_backed_gold_files": sorted(path_backed),
        "gold_path_lengths": path_lengths,
        "provenance": list(bundle.get("provenance") or []),
    }
    for key in ("direct_target_count", "covered_direct_targets", "task_tokens", "branch_decisions"):
        if key in selection:
            row[key] = selection[key]

    if provider is not None and candidates:
        started = time.perf_counter()
        reranked, judgment, state = rerank_frontier(
            {"description": description},
            bundle,
            candidates,
            provider,
        )
        row["provider_elapsed_seconds"] = round(time.perf_counter() - started, 6)
        reranked_files = _ranked_file_order(root, reranked)
        row["reranked_file_order"] = reranked_files
        row["reranked"] = _file_metrics(
            reranked_files, gold_existing, ks=ks, path_backed_files=path_backed
        )
        row["judgment_scores"] = [
            {
                "candidate_id": item.candidate_id,
                "candidate": str(
                    item.candidate.get("qualified_name")
                    or item.candidate.get("name")
                    or item.candidate_id
                ),
                "path": _candidate_path(item.candidate),
                "baseline_rank": item.baseline_rank,
                "reranked_rank": index,
                "probability": (
                    float(item.judgment_probability)
                    if item.judgment_probability is not None
                    else None
                ),
            }
            for index, item in enumerate(reranked, 1)
        ]
        row["provider_state_tokens"] = estimate_tokens(state)
        if judgment is not None:
            row["usage"] = dict(judgment.usage)
            row["model"] = judgment.model
            row["request_id"] = judgment.request_id
    return row


def run_graph_task(
    context: StoredSnapshotContext,
    task: Mapping[str, Any],
    retrieval_spec: Mapping[str, Any],
    adaptive_spec: Mapping[str, Any],
    provider=None,
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, Any]:
    root = context.query.resolve(str(task["root"]))
    gold_existing, gold_novel = _gold_files(context, task)
    if not gold_existing:
        raise ValueError(
            "v1F task %r has no changed production file present in pre-fix snapshot"
            % task["id"]
        )

    max_depth = int(retrieval_spec.get("max_depth", 3))
    direct = _direct_selection(
        context, root, max_candidates=int(retrieval_spec["direct_max_candidates"])
    )
    naive = _naive_selection(
        context,
        root,
        max_depth=max_depth,
        max_candidates=int(retrieval_spec["naive_max_candidates"]),
    )
    adaptive = _adaptive_selection(
        context,
        root,
        str(task["description"]),
        max_depth=max_depth,
        max_candidates=int(retrieval_spec["adaptive_max_candidates"]),
        max_branch_expansions_per_depth=int(
            adaptive_spec["max_branch_expansions_per_depth"]
        ),
        fallback_branch_expansions=int(
            adaptive_spec.get("fallback_branch_expansions", 1)
        ),
    )

    direct_row = _row(
        context, root, direct, gold_existing, str(task["description"]), ks=ks
    )
    naive_row = _row(
        context, root, naive, gold_existing, str(task["description"]), ks=ks
    )
    adaptive_row = _row(
        context,
        root,
        adaptive,
        gold_existing,
        str(task["description"]),
        ks=ks,
        provider=provider,
    )
    direct_row["false_complete"] = bool(
        direct_row["declared_complete"]
        and bool(direct_row["baseline"]["missing_gold_files"])
    )
    return {
        "id": task["id"],
        "source_pr": task["source_pr"],
        "pre_fix_revision": task["pre_fix_revision"],
        "description": task["description"],
        "root": task["root"],
        "gold_changed_files": sorted(
            {_normalize_path(str(path)) for path in task["gold_changed_files"]}
        ),
        "gold_existing_files": sorted(gold_existing),
        "gold_novel_files": sorted(gold_novel),
        "snapshot_id": context.snapshot.snapshot_id,
        "repository_key": context.snapshot.repository_key,
        "direct": direct_row,
        "naive": naive_row,
        "adaptive": adaptive_row,
    }


def _summary(tasks: Sequence[Mapping[str, Any]], key: str) -> Dict[str, Any]:
    rows = [task[key] for task in tasks]
    payload: Dict[str, Any] = {
        "mean_candidate_count": sum(float(row["candidate_count"]) for row in rows) / len(rows),
        "mean_context_file_count": sum(float(row["context_file_count"]) for row in rows) / len(rows),
        "mean_compact_path_state_tokens": sum(float(row["compact_path_state_tokens"]) for row in rows) / len(rows),
        "mean_expansion_count": sum(float(row["expansion_count"] or 0) for row in rows) / len(rows),
        "baseline": _average([row["baseline"] for row in rows]),
    }
    reranked = [row["reranked"] for row in rows if "reranked" in row]
    if reranked:
        payload["reranked"] = _average(reranked)
        usage = {"input_tokens": 0, "output_tokens": 0}
        elapsed = 0.0
        for row in rows:
            elapsed += float(row.get("provider_elapsed_seconds") or 0.0)
            for token_key in usage:
                value = (row.get("usage") or {}).get(token_key)
                if isinstance(value, (int, float)):
                    usage[token_key] += value
        payload["usage"] = usage
        payload["provider_elapsed_seconds"] = round(elapsed, 6)
    return payload


def run_historical_experiment(
    repository_path: str,
    spec: Mapping[str, Any],
    provider=None,
) -> Dict[str, Any]:
    _validate_spec(spec)
    repo = Path(repository_path).resolve()
    if not (repo / ".git").exists():
        raise ValueError("v1F repository path must be a local Git checkout")

    retrieval_spec = spec["retrieval"]
    adaptive_spec = spec["adaptive"]
    repository_name = str((spec.get("repository") or {}).get("name") or repo.name)
    rows: List[Dict[str, Any]] = []
    for task in spec["tasks"]:
        with tempfile.TemporaryDirectory(prefix="feynmap-v1f-") as temp:
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
                    "source_revision": str(task["pre_fix_revision"]),
                },
            )
            context = StoredSnapshotContext(snapshot, graph)
            rows.append(
                run_graph_task(
                    context,
                    task,
                    retrieval_spec,
                    adaptive_spec,
                    provider,
                )
            )

    false_complete = sum(1 for task in rows if task["direct"]["false_complete"])
    novel_count = sum(len(task["gold_novel_files"]) for task in rows)
    return {
        "schema": V1F_SCHEMA,
        "name": spec.get("name"),
        "repository": str(repo),
        "task_count": len(rows),
        "historical_ground_truth": {
            "changed_existing_files": sum(len(task["gold_existing_files"]) for task in rows),
            "novel_files_excluded_from_retrieval_scoring": novel_count,
        },
        "direct_summary": _summary(rows, "direct"),
        "naive_summary": _summary(rows, "naive"),
        "adaptive_summary": _summary(rows, "adaptive"),
        "false_completeness": {
            "count": false_complete,
            "rate": false_complete / float(len(rows)) if rows else None,
        },
        "tasks": rows,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Context Ranker v1F historical change-localization experiment"
    )
    parser.add_argument("repository", help="Local Git checkout of the external repository")
    parser.add_argument("--spec", default="experiments/context_ranker_v1f.json")
    parser.add_argument("--task", action="append", default=[], help="Run only the named task id; may be repeated")
    parser.add_argument("--jev", action="store_true", help="Use the frozen v1E Jev reranker on adaptive candidates")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    with open(args.spec, "r", encoding="utf-8") as handle:
        spec = json.load(handle)
    if args.task:
        selected = set(args.task)
        spec = dict(spec)
        spec["tasks"] = [task for task in spec["tasks"] if task.get("id") in selected]
        missing = selected - {str(task.get("id")) for task in spec["tasks"]}
        if missing:
            raise ValueError("unknown v1F task ids: %s" % ", ".join(sorted(missing)))
    provider = JevJudgmentProvider() if args.jev else None
    result = run_historical_experiment(args.repository, spec, provider)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
