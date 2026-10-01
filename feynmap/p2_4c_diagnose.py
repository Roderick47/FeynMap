"""Post-hoc diagnostics for the two preserved P2.4b behavioral misses.

This module intentionally does not score or tune against the frozen P2.4b gold
patterns. It records the existing pipeline's selected symbols, extracted source
observations, deterministic relevance decisions, and delivered behavioral
witnesses so a later development slice can classify the failure layer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .behavioral_context import BehaviorEvidenceBudget, BehavioralContextBuilder
from .context_pipeline import SparseContextPipeline
from .delivery_channels import DeliveryChannelPolicy
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .relevance import DeterministicRelevanceJudge


TASK_IDS = ("overpayment-regression-test", "retry-policy")


def _node_row(graph, node_id: str) -> Dict[str, Any]:
    node = graph.node(node_id)
    if node is None:
        return {"id": node_id, "missing": True}
    return {
        "id": node.id,
        "name": node.name,
        "kind": node.kind.value if hasattr(node.kind, "value") else str(node.kind),
        "path": node.location.path if node.location is not None else None,
        "line": node.location.line if node.location is not None else None,
    }


def run_diagnostics(manifest_path: Path) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest: Mapping[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = manifest_path.parent.parent
    project_root = (repo_root / manifest["source"]["root"]).resolve()

    graph = FeynMapEngine().analyze(
        str(project_root),
        language=str(manifest["source"]["language"]),
        framework=str(manifest["source"]["framework"]),
    )
    context_spec = manifest["context_budget"]
    context_budget = MinimalContextBudget(
        max_tokens=int(context_spec["max_tokens"]),
        max_nodes=int(context_spec["max_nodes"]),
        max_edges=int(context_spec["max_edges"]),
    )
    behavior_spec = manifest["behavior_budget"]
    behavior_budget = BehaviorEvidenceBudget(
        max_tokens=int(behavior_spec["max_tokens"]),
        max_observations=int(behavior_spec["max_observations"]),
        max_source_chars=int(behavior_spec["max_source_chars"]),
    )
    activation = manifest["activation"]
    sparse_pipeline = SparseContextPipeline(graph)
    judge = DeterministicRelevanceJudge()
    builder = BehavioralContextBuilder(
        graph,
        project_root,
        judge=judge,
        budget=behavior_budget,
    )
    delivery_policy = DeliveryChannelPolicy(mode="symbol_evidence")

    tasks = {str(task["id"]): task for task in manifest["tasks"]}
    records = []
    for task_id in TASK_IDS:
        task = tasks[task_id]
        query = str(task["query"])
        sparse = sparse_pipeline.concept(
            query,
            context_budget=context_budget,
            delivery_policy=delivery_policy,
            seed_limit=int(activation["seed_limit"]),
            candidate_limit=int(activation["candidate_limit"]),
            max_depth=int(activation["max_depth"]),
            beam_width=int(activation["beam_width"]),
            max_nodes=int(activation["max_nodes"]),
            direction=str(activation["direction"]),
        )
        profile = judge.profile(query)
        candidates = builder.extractor.extract(graph, sparse.context.selected_node_ids)
        decisions = dict(judge.rank(query, candidates, profile))
        behavioral = builder.build(query, sparse.context, budget=behavior_budget)
        delivered_ids = {item.id for item in behavioral.delivered_observations}

        observation_rows = []
        for observation in candidates:
            node = graph.node(observation.symbol_id)
            decision = decisions.get(observation.id)
            observation_rows.append(
                {
                    "id": observation.id,
                    "symbol_id": observation.symbol_id,
                    "symbol_name": node.name if node is not None else None,
                    "path": observation.location.path,
                    "line": observation.location.line,
                    "kind": observation.kind.value,
                    "summary": observation.summary,
                    "source": observation.source,
                    "condition": observation.condition,
                    "relevance": decision.to_dict() if decision is not None else None,
                    "delivered": observation.id in delivered_ids,
                }
            )

        records.append(
            {
                "task_id": task_id,
                "query": query,
                "profile": profile.to_dict(),
                "sparse": {
                    "sufficient": bool(sparse.context.sufficient),
                    "unresolved": list(sparse.context.unresolved_query_identifiers),
                    "selected_nodes": [
                        _node_row(graph, node_id)
                        for node_id in sparse.context.selected_node_ids
                    ],
                    "selected_edges": list(sparse.context.selected_edge_ids),
                },
                "behavior": {
                    "sufficient": bool(behavioral.sufficient),
                    "behavior_tokens": behavioral.behavior_tokens,
                    "candidate_count": behavioral.candidate_observations,
                    "delivered_count": len(behavioral.delivered_observations),
                    "omitted_relevant": behavioral.omitted_relevant_observations,
                    "omitted_critical": behavioral.omitted_critical_observations,
                    "observations": observation_rows,
                },
            }
        )

    return {
        "schema": "feynmap.p2_4c_gap_diagnostics.v1",
        "status": "posthoc_development_diagnostic_only",
        "source_checkpoint": "P2.4b accepted 13/15 fresh result",
        "gold_patterns_used_for_routing_or_packing": False,
        "records": records,
    }


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="experiments/p2_4b_behavior_manifest.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = run_diagnostics(Path(args.manifest))
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": result["status"],
        "tasks": [item["task_id"] for item in result["records"]],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
