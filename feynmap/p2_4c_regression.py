"""P2.4c development replay over the already-seen P2.4b corpus.

This is regression evidence only. The P2.4b 13/15 result remains the canonical
fresh checkpoint; this module verifies that the later generalized repairs close
the two diagnosed gaps without losing previously delivered evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from .behavioral_context import BehaviorEvidenceBudget
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .p2_4b_evaluate import _load_manifest, _verify_source_blobs
from .task_evidence import TaskConditionedEvidencePipeline


def _flatten_values(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            for nested in _flatten_values(item):
                yield nested
    elif isinstance(value, (list, tuple)):
        for item in value:
            for nested in _flatten_values(item):
                yield nested
    elif value is not None:
        yield str(value)


def _payload_text(payload: Mapping[str, Any]) -> str:
    return "\n".join(_flatten_values(payload)).casefold()


def _score(task: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    text = _payload_text(payload)
    rows = []
    for pattern in task.get("required_behavior_patterns", []):
        matched = False
        for alternative in pattern.get("alternatives", []):
            if all(str(phrase).casefold() in text for phrase in alternative):
                matched = True
                break
        rows.append({"id": str(pattern["id"]), "matched": matched})
    return {
        "required": len(rows),
        "matched": sum(1 for row in rows if row["matched"]),
        "patterns": rows,
    }


def run_regression(manifest_path: Path) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_path)
    repo_root = manifest_path.parent.parent
    project_root = (repo_root / manifest["source"]["root"]).resolve()
    _verify_source_blobs(manifest, project_root)

    graph = FeynMapEngine().analyze(
        str(project_root),
        language=str(manifest["source"]["language"]),
        framework=str(manifest["source"]["framework"]),
    )
    if graph.diagnostics.get("errors"):
        raise ValueError("P2.4c graph errors: %r" % graph.diagnostics["errors"][:3])

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
    pipeline = TaskConditionedEvidencePipeline(
        graph,
        project_root,
        behavior_budget=behavior_budget,
    )

    records = []
    total_required = 0
    total_matched = 0
    missing_control_ok = True
    sparse_caps_ok = True
    behavior_caps_ok = True

    for task in manifest["tasks"]:
        query = str(task["query"])
        result = pipeline.concept(
            query,
            context_budget=context_budget,
            behavior_budget=behavior_budget,
            seed_limit=int(activation["seed_limit"]),
            candidate_limit=int(activation["candidate_limit"]),
            max_depth=int(activation["max_depth"]),
            beam_width=int(activation["beam_width"]),
            max_nodes=int(activation["max_nodes"]),
            direction=str(activation["direction"]),
        )
        score = _score(task, result.payload)
        total_required += score["required"]
        total_matched += score["matched"]
        sparse_cap_ok = result.sparse.context.delivered_tokens <= context_budget.max_tokens
        behavior_cap_ok = result.behavioral.behavior_tokens <= behavior_budget.max_tokens
        sparse_caps_ok = sparse_caps_ok and sparse_cap_ok
        behavior_caps_ok = behavior_caps_ok and behavior_cap_ok

        expected_missing = list(task.get("expected_missing_identifiers", []))
        control_ok = True
        if expected_missing:
            unresolved = set(result.sparse.context.unresolved_query_identifiers)
            observations = _payload_text(
                {"observations": result.payload["behavioral_evidence"]["observations"]}
            )
            control_ok = (
                all(identifier in unresolved for identifier in expected_missing)
                and not result.sufficient
                and all(identifier.casefold() not in observations for identifier in expected_missing)
            )
            missing_control_ok = missing_control_ok and control_ok

        records.append({
            "task_id": str(task["id"]),
            "pattern_score": score,
            "sparse_tokens": result.sparse.context.delivered_tokens,
            "behavior_tokens": result.behavioral.behavior_tokens,
            "combined_tokens": result.behavioral.total_tokens,
            "continuation": result.continuation.to_dict(),
            "sparse_within_budget": sparse_cap_ok,
            "behavior_within_budget": behavior_cap_ok,
            "sufficient": bool(result.sufficient),
            "unresolved": list(result.sparse.context.unresolved_query_identifiers),
            "missing_identifier_control_ok": control_ok,
        })

    return {
        "schema": "feynmap.p2_4c_development_regression.v1",
        "status": "development_regression_on_seen_p2_4b_corpus",
        "canonical_fresh_checkpoint": {
            "phase": "P2.4b",
            "matched_patterns": 13,
            "required_patterns": 15,
            "note": "P2.4b remains the frozen fresh result; P2.4c does not rewrite it.",
        },
        "matched_patterns": total_matched,
        "required_patterns": total_required,
        "pattern_recall": round(
            float(total_matched) / float(total_required) if total_required else 1.0,
            6,
        ),
        "all_sparse_packets_within_budget": sparse_caps_ok,
        "all_behavior_packets_within_budget": behavior_caps_ok,
        "missing_identifier_control_ok": missing_control_ok,
        "records": records,
        "claim_scope": "development regression only; not fresh evaluation, downstream answer accuracy, or hallucination reduction",
    }


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="experiments/p2_4b_behavior_manifest.json"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = run_regression(Path(args.manifest))
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": result["status"],
        "matched_patterns": result["matched_patterns"],
        "required_patterns": result["required_patterns"],
        "pattern_recall": result["pattern_recall"],
        "missing_identifier_control_ok": result["missing_identifier_control_ok"],
        "all_sparse_packets_within_budget": result["all_sparse_packets_within_budget"],
        "all_behavior_packets_within_budget": result["all_behavior_packets_within_budget"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
