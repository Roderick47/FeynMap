"""R1 assisted-arm context generation.

This module closes the gap between the provider-neutral repair benchmark and
FeynMap's grounding experiments. It creates oracle-free context for the three
assisted R1 arms from a sanitized repository copy.

The candidate pool is shared across arms. Deterministic context uses a stable
task-text + graph-structure order. Relevance context only reranks that pool.
Dual-channel context preserves relevance order and adds non-destructive repair
role guidance; role judgments never filter or reorder context.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import EdgeKind, SemanticEdge, SemanticNode
from ..core.model import TIER_RANK
from ..engine import FeynMapEngine
from ..snapshots import capture_repository_snapshot
from .ai_repair_benchmark import ARMS, load_json, validate_spec
from .ai_repair_execution import (
    _copy_repository,
    repository_content_hash,
    resolve_source_repository,
)
from .contracts import JudgmentProvider, JudgmentQuestion
from .jev import JevJudgmentProvider
from .ranking import rerank_with_judgments_result
from .repair_role_v1j import (
    REPAIR_ROLES,
    ROLE_CRITERIA,
    ROLE_PROMPT,
    _role_probabilities,
)
from .repair_role_v1m import coherent_role_distribution
from .repair_role_v1q import _role_lanes, _target_order

CONTEXT_SCHEMA = "feynmap.ai_repair_context.v1"
ASSISTED_ARMS = tuple(arm for arm in ARMS if arm != "unassisted")
DEFAULT_MAX_CANDIDATES = 32
DEFAULT_MAX_RELATIONSHIPS = 64
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
NON_BEHAVIORAL = {EdgeKind.CONTAINS, EdgeKind.OWNS, EdgeKind.IMPORTS}


def _task(spec: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    for task in spec["tasks"]:
        if str(task["id"]) == task_id:
            return task
    raise ValueError("unknown repair benchmark task: %s" % task_id)


def _tokens(value: str) -> set:
    text = str(value or "")
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {token.casefold() for token in TOKEN_RE.findall(split) if len(token) > 1}


def _location(node: SemanticNode) -> Optional[Dict[str, Any]]:
    if node.location is None:
        return None
    return {
        "path": node.location.path,
        "line": node.location.line,
        "end_line": node.location.end_line,
    }


def _compact_evidence(node: SemanticNode) -> List[Dict[str, Any]]:
    rows = []
    for item in node.evidence[:2]:
        row = {
            "kind": item.kind.value,
            "detector": item.detector,
            "confidence": item.confidence,
        }
        if item.location is not None:
            row["location"] = {
                "path": item.location.path,
                "line": item.location.line,
                "end_line": item.location.end_line,
            }
        rows.append(row)
    return rows


def _compact_candidate(node: SemanticNode) -> Dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "kind": node.kind.value,
        "language": node.language,
        "framework": node.framework,
        "confidence_tier": node.confidence_tier.value,
        "location": _location(node),
        "evidence": _compact_evidence(node),
    }


def _compact_relationship(edge: SemanticEdge) -> Dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "relationship": edge.kind.value,
        "confidence_tier": edge.confidence_tier.value,
    }


def _candidate_score(
    node: SemanticNode,
    task_tokens: set,
    incoming: Mapping[str, Sequence[SemanticEdge]],
    outgoing: Mapping[str, Sequence[SemanticEdge]],
) -> Tuple[float, int, int]:
    location = node.location.path if node.location is not None else ""
    text = " ".join(
        value
        for value in (node.name, node.qualified_name or "", location)
        if value
    )
    overlap = len(task_tokens & _tokens(text))
    in_edges = list(incoming.get(node.id, ()))
    out_edges = list(outgoing.get(node.id, ()))
    behavioral = sum(
        1 for edge in in_edges + out_edges if edge.kind not in NON_BEHAVIORAL
    )
    boundary_kinds = {
        edge.kind
        for edge in in_edges + out_edges
        if edge.kind
        in {
            EdgeKind.RENDERS,
            EdgeKind.LOADS,
            EdgeKind.REQUESTS,
            EdgeKind.ROUTES_TO,
            EdgeKind.CONNECTS_TO,
            EdgeKind.INVOKES,
            EdgeKind.DEPENDS_ON,
            EdgeKind.EXTENDS,
            EdgeKind.EMITS,
            EdgeKind.SUBSCRIBES,
            EdgeKind.FLOWS_TO,
            EdgeKind.SPAWNS,
        }
    }
    score = (
        12.0 * overlap
        + min(behavioral, 8) * 0.75
        + min(len(boundary_kinds), 4) * 0.5
        + TIER_RANK[node.confidence_tier] * 0.05
    )
    return score, overlap, behavioral


def _candidate_pool(
    graph,
    description: str,
    *,
    max_candidates: int,
    max_relationships: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    incoming = {node.id: graph.incoming(node.id) for node in graph.nodes}
    outgoing = {node.id: graph.outgoing(node.id) for node in graph.nodes}
    task_tokens = _tokens(description)
    scored = []
    for node in graph.nodes:
        if node.location is None:
            continue
        # Repository root and external systems are not source edit candidates.
        if node.id == "repository:root" or node.kind.value == "external_system":
            continue
        score, overlap, behavioral = _candidate_score(
            node, task_tokens, incoming, outgoing
        )
        scored.append((score, overlap, behavioral, node))
    scored.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            -item[2],
            item[3].id,
        )
    )
    selected_nodes = [item[3] for item in scored[: max(1, int(max_candidates))]]
    selected_ids = {node.id for node in selected_nodes}
    candidates = []
    diagnostics = []
    for rank, (score, overlap, behavioral, node) in enumerate(
        scored[: max(1, int(max_candidates))], 1
    ):
        candidate = _compact_candidate(node)
        candidate["deterministic_rank"] = rank
        candidates.append(candidate)
        diagnostics.append(
            {
                "candidate_id": node.id,
                "score": round(score, 6),
                "task_token_overlap": overlap,
                "behavioral_degree": behavioral,
            }
        )

    edge_rows = [
        edge
        for edge in graph.edges
        if edge.source in selected_ids and edge.target in selected_ids
    ]
    edge_rows.sort(
        key=lambda edge: (
            edge.kind in NON_BEHAVIORAL,
            -TIER_RANK[edge.confidence_tier],
            edge.kind.value,
            edge.source,
            edge.target,
            edge.id,
        )
    )
    relationships = [
        _compact_relationship(edge)
        for edge in edge_rows[: max(1, int(max_relationships))]
    ]
    return candidates, relationships, {
        "task_tokens": sorted(task_tokens),
        "candidate_scores": diagnostics,
        "available_local_candidate_count": len(scored),
        "available_internal_relationship_count": len(edge_rows),
    }


def _seed_identity(root: Path, task: Mapping[str, Any]) -> None:
    """Give sanitized temporary copies stable repository identity metadata."""
    git_dir = root / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    revision = str(task["repository"]["revision"])
    task_id = str(task["id"])
    (git_dir / "HEAD").write_text(revision + "\n", encoding="utf-8")
    (git_dir / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n'
        '[remote "origin"]\n\turl = https://benchmark.invalid/%s.git\n' % task_id,
        encoding="utf-8",
    )


def _base_context(
    spec: Mapping[str, Any],
    task: Mapping[str, Any],
    arm: str,
    project_root: Path,
    *,
    max_candidates: int,
    max_relationships: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    repository = task["repository"]
    task_id = str(task["id"])
    timings: Dict[str, float] = {}
    total_started = time.perf_counter()

    source = resolve_source_repository(project_root, str(repository["locator"]))
    stage_started = time.perf_counter()
    actual_hash = repository_content_hash(
        source, policy=str(repository["content_hash_policy"])
    )
    timings["repository_hash_seconds"] = time.perf_counter() - stage_started
    if actual_hash != str(repository["content_hash"]):
        raise ValueError(
            "repair benchmark repository content hash mismatch for task %s"
            % task["id"]
        )
    print(
        "[context:%s] repository hash %.1fs" % (
            task_id, timings["repository_hash_seconds"]
        ),
        file=sys.stderr,
        flush=True,
    )

    sealed = [str(path) for path in task["oracle"].get("sealed_files") or []]
    with tempfile.TemporaryDirectory(prefix="feynmap-r1-context-") as temp:
        sanitized = Path(temp) / "repository"

        stage_started = time.perf_counter()
        _copy_repository(source, sanitized, excluded_files=sealed)
        _seed_identity(sanitized, task)
        timings["copy_sanitize_seconds"] = time.perf_counter() - stage_started
        print(
            "[context:%s] copy/sanitize %.1fs" % (
                task_id, timings["copy_sanitize_seconds"]
            ),
            file=sys.stderr,
            flush=True,
        )

        stage_started = time.perf_counter()
        graph = FeynMapEngine().analyze(str(sanitized))
        timings["analysis_seconds"] = time.perf_counter() - stage_started
        print(
            "[context:%s] FeynMap analysis %.1fs (%d nodes, %d edges)" % (
                task_id,
                timings["analysis_seconds"],
                len(graph.nodes),
                len(graph.edges),
            ),
            file=sys.stderr,
            flush=True,
        )

        stage_started = time.perf_counter()
        snapshot = capture_repository_snapshot(
            sanitized,
            graph,
            analysis_options={
                "experiment": "ai_repair_r1_context",
                "task_id": str(task["id"]),
                "sealed_oracles_excluded": True,
            },
        )
        timings["snapshot_seconds"] = time.perf_counter() - stage_started
        print(
            "[context:%s] snapshot/hash %.1fs" % (
                task_id, timings["snapshot_seconds"]
            ),
            file=sys.stderr,
            flush=True,
        )

        stage_started = time.perf_counter()
        candidates, relationships, selection = _candidate_pool(
            graph,
            str(task["description"]),
            max_candidates=max_candidates,
            max_relationships=max_relationships,
        )
        timings["candidate_pool_seconds"] = time.perf_counter() - stage_started
        print(
            "[context:%s] candidate pool %.1fs" % (
                task_id, timings["candidate_pool_seconds"]
            ),
            file=sys.stderr,
            flush=True,
        )

    timings["total_seconds"] = time.perf_counter() - total_started
    print(
        "[context:%s] total %.1fs" % (task_id, timings["total_seconds"]),
        file=sys.stderr,
        flush=True,
    )

    context = {
        "schema": CONTEXT_SCHEMA,
        "task_id": str(task["id"]),
        "arm": arm,
        "source_repository": {
            "revision": str(repository["revision"]),
            "content_hash": str(repository["content_hash"]),
            "content_hash_policy": str(repository["content_hash_policy"]),
        },
        "analysis_snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "repository_key": snapshot.repository_key,
            "revision": snapshot.revision,
            "content_hash": snapshot.content_hash,
            "graph_hash": snapshot.graph_hash,
        },
        "policy": {
            "candidate_pool_shared_across_assisted_arms": True,
            "oracle_files_excluded_before_analysis": True,
            "gold_labels_used_for_selection": False,
            "language_or_framework_rules": False,
            "max_candidates": int(max_candidates),
            "max_relationships": int(max_relationships),
        },
        "performance": {
            key: round(float(value), 6)
            for key, value in timings.items()
        },
        "candidates": candidates,
        "relationships": relationships,
        "selection": selection,
    }
    return context, candidates, relationships


def _relevance_rerank(
    description: str,
    candidates: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
    provider: JudgmentProvider,
):
    ranked, result = rerank_with_judgments_result(
        {"description": description},
        candidates,
        provider,
        shared_state={
            "relationships": [dict(row) for row in relationships],
            "selection_note": (
                "All candidates come from one bounded deterministic repository-wide "
                "pool. Presence does not imply relevance or a need to edit."
            ),
        },
    )
    rows = []
    for rank, item in enumerate(ranked, 1):
        row = dict(item.candidate)
        row["relevance_rank"] = rank
        row["semantic_relevance_probability"] = float(
            item.judgment_probability or 0.0
        )
        rows.append(row)
    return rows, result


def _role_guidance(
    description: str,
    candidates: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
    provider: JudgmentProvider,
) -> Tuple[Dict[str, Any], Any]:
    state = {
        "task": {"description": description},
        "candidates": [dict(row) for row in candidates],
        "grounded_context": {
            "relationships": [dict(row) for row in relationships],
            "selection_note": (
                "Context order is owned by semantic relevance. Repair roles are "
                "advisory and must not filter or reorder candidates."
            ),
        },
    }
    questions = {
        "role_%d" % index: JudgmentQuestion.choice(
            ROLE_PROMPT % str(candidate["id"]),
            ROLE_CRITERIA,
        )
        for index, candidate in enumerate(candidates)
    }
    result = provider.evaluate(state, questions)
    annotations = []
    for index, candidate in enumerate(candidates):
        answer = result.answers["role_%d" % index]
        probabilities = _role_probabilities(answer)
        source = {
            "candidate_id": str(candidate["id"]),
            "semantic_relevance_probability": float(
                candidate.get("semantic_relevance_probability") or 0.0
            ),
            "predicted_repair_role": str(answer.value),
            "repair_role_probabilities": probabilities,
        }
        coherent = coherent_role_distribution(source)
        source["coherent_role_probabilities"] = coherent
        source["coherent_repair_role"] = max(
            REPAIR_ROLES, key=lambda role: (coherent[role], role)
        )
        annotations.append(source)

    target_order = _target_order(annotations)
    lanes = _role_lanes(annotations)
    return {
        "context_order_changed_by_roles": False,
        "candidate_retention_ratio": 1.0,
        "edit_target_candidate_order": target_order,
        "role_lanes": lanes,
        "annotations": annotations,
    }, result


def generate_context(
    spec: Mapping[str, Any],
    task_id: str,
    arm: str,
    *,
    project_root: Path,
    provider: Optional[JudgmentProvider] = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_relationships: int = DEFAULT_MAX_RELATIONSHIPS,
) -> Dict[str, Any]:
    validate_spec(spec)
    if arm not in ASSISTED_ARMS:
        raise ValueError(
            "R1 context generation only supports assisted arms: %s"
            % ", ".join(ASSISTED_ARMS)
        )
    if max_candidates <= 0 or max_relationships <= 0:
        raise ValueError("R1 context bounds must be positive")
    task = _task(spec, task_id)
    context, candidates, relationships = _base_context(
        spec,
        task,
        arm,
        project_root,
        max_candidates=max_candidates,
        max_relationships=max_relationships,
    )

    if arm == "deterministic_context":
        context["generation"] = {
            "judgment_provider_used": False,
            "context_order_owner": "deterministic_task_graph_score",
        }
        return context

    if provider is None:
        raise ValueError("%s requires an explicit judgment provider" % arm)

    relevance_rows, relevance_result = _relevance_rerank(
        str(task["description"]), candidates, relationships, provider
    )
    context["candidates"] = relevance_rows
    context["generation"] = {
        "judgment_provider_used": True,
        "context_order_owner": "semantic_relevance",
        "relevance": {
            "provider": relevance_result.provider,
            "model": relevance_result.model,
            "request_id": relevance_result.request_id,
            "usage": dict(relevance_result.usage),
        },
    }

    if arm == "relevance_context":
        return context

    guidance, role_result = _role_guidance(
        str(task["description"]),
        relevance_rows,
        relationships,
        provider,
    )
    context["repair_guidance"] = guidance
    context["generation"]["roles"] = {
        "provider": role_result.provider,
        "model": role_result.model,
        "request_id": role_result.request_id,
        "usage": dict(role_result.usage),
        "policy": "non_destructive_dual_channel_v1q",
    }
    return context


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate oracle-free FeynMap context for one assisted R1 arm"
    )
    parser.add_argument("spec")
    parser.add_argument("--task", required=True)
    parser.add_argument("--arm", required=True, choices=ASSISTED_ARMS)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument(
        "--max-relationships", type=int, default=DEFAULT_MAX_RELATIONSHIPS
    )
    parser.add_argument(
        "--jev",
        action="store_true",
        help="Use Jev for relevance/dual-channel judgment",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    spec = load_json(Path(args.spec))
    provider = JevJudgmentProvider() if args.jev else None
    result = generate_context(
        spec,
        args.task,
        args.arm,
        project_root=Path(args.project_root),
        provider=provider,
        max_candidates=args.max_candidates,
        max_relationships=args.max_relationships,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
