"""P2.4b fresh, source-locked behavioral evidence comparison.

The manifest/source fixture was frozen before this evaluator existed.  Context
construction uses only each task's query.  Gold behavior patterns are read only
after both arms have already produced their model-facing payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .behavioral_context import BehaviorEvidenceBudget, BehavioralContextBuilder
from .context_pipeline import SparseContextPipeline
from .delivery_channels import DeliveryChannelPolicy
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .relevance import DeterministicRelevanceJudge


FROZEN_MANIFEST_GIT_BLOB = "5900e1f64cb482a720cb12ad7fd87d0ccb176172"


def git_blob_sha(path: Path) -> str:
    raw = Path(path).read_bytes()
    header = ("blob %d\0" % len(raw)).encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _load_manifest(path: Path) -> Mapping[str, Any]:
    actual = git_blob_sha(path)
    if actual != FROZEN_MANIFEST_GIT_BLOB:
        raise ValueError(
            "P2.4b manifest changed after freeze: expected %s got %s"
            % (FROZEN_MANIFEST_GIT_BLOB, actual)
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "feynmap.p2_4b_behavior_fidelity_manifest.v1":
        raise ValueError("unexpected P2.4b manifest schema")
    return value


def _verify_source_blobs(manifest: Mapping[str, Any], project_root: Path) -> None:
    expected = manifest["source"]["blobs"]
    for relative, expected_sha in sorted(expected.items()):
        path = project_root / relative
        if not path.is_file():
            raise ValueError("P2.4b frozen source missing: %s" % relative)
        actual = git_blob_sha(path)
        if actual != expected_sha:
            raise ValueError(
                "P2.4b source changed after freeze: %s expected %s got %s"
                % (relative, expected_sha, actual)
            )


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


def _pattern_matches(pattern: Mapping[str, Any], text: str) -> bool:
    for alternative in pattern.get("alternatives", []):
        if all(str(phrase).casefold() in text for phrase in alternative):
            return True
    return False


def _score_patterns(task: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    text = _payload_text(payload)
    rows = []
    for pattern in task.get("required_behavior_patterns", []):
        matched = _pattern_matches(pattern, text)
        rows.append({"id": pattern["id"], "matched": matched})
    return {
        "required": len(rows),
        "matched": sum(1 for row in rows if row["matched"]),
        "patterns": rows,
    }


def _observation_text(behavioral) -> str:
    parts: List[str] = []
    for observation in behavioral.delivered_observations:
        parts.append(observation.summary)
        if observation.source:
            parts.append(observation.source)
        if observation.condition:
            parts.append(observation.condition)
    return "\n".join(parts).casefold()


def run_evaluation(manifest_path: Path, *, output: Path = None) -> Dict[str, Any]:
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
        raise ValueError("P2.4b graph errors: %r" % graph.diagnostics["errors"][:3])

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
    behavior_builder = BehavioralContextBuilder(
        graph,
        project_root,
        judge=DeterministicRelevanceJudge(),
        budget=behavior_budget,
    )
    delivery_policy = DeliveryChannelPolicy(mode="symbol_evidence")

    # First pass: build all model-facing contexts using only task id + query.
    # Gold patterns/support labels are deliberately untouched here.
    built: Dict[str, Dict[str, Any]] = {}
    for task in manifest["tasks"]:
        task_id = str(task["id"])
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
        behavioral = behavior_builder.build(
            query,
            sparse.context,
            budget=behavior_budget,
        )
        built[task_id] = {
            "query": query,
            "sparse": sparse,
            "behavioral": behavioral,
        }

    # Second pass: scoring-only access to preregistered labels.
    records: List[Dict[str, Any]] = []
    total_required = 0
    symbol_matched = 0
    behavior_matched = 0
    behavior_caps_ok = True
    no_task_regressions = True
    missing_control_ok = True

    for task in manifest["tasks"]:
        task_id = str(task["id"])
        row = built[task_id]
        sparse = row["sparse"]
        behavioral = row["behavioral"]
        symbol_score = _score_patterns(task, sparse.context.payload)
        behavior_score = _score_patterns(task, behavioral.payload)
        total_required += int(symbol_score["required"])
        symbol_matched += int(symbol_score["matched"])
        behavior_matched += int(behavior_score["matched"])
        if behavior_score["matched"] < symbol_score["matched"]:
            no_task_regressions = False
        cap_ok = behavioral.behavior_tokens <= behavior_budget.max_tokens
        behavior_caps_ok = behavior_caps_ok and cap_ok

        expected_missing = list(task.get("expected_missing_identifiers", []))
        control_ok = True
        if expected_missing:
            unresolved = list(sparse.context.unresolved_query_identifiers)
            observation_text = _observation_text(behavioral)
            control_ok = (
                all(identifier in unresolved for identifier in expected_missing)
                and not sparse.context.sufficient
                and not behavioral.sufficient
                and all(identifier.casefold() not in observation_text for identifier in expected_missing)
            )
            missing_control_ok = missing_control_ok and control_ok

        records.append(
            {
                "task_id": task_id,
                "query": row["query"],
                "expected_status": task["expected_status"],
                "symbol_evidence": {
                    "context_tokens": sparse.context.delivered_tokens,
                    "selected_nodes": len(sparse.context.selected_node_ids),
                    "selected_edges": len(sparse.context.selected_edge_ids),
                    "sufficient": bool(sparse.context.sufficient),
                    "unresolved_query_identifiers": list(
                        sparse.context.unresolved_query_identifiers
                    ),
                    "pattern_score": symbol_score,
                },
                "behavior_deterministic": {
                    "behavior_tokens": behavioral.behavior_tokens,
                    "combined_tokens": behavioral.total_tokens,
                    "candidate_observations": behavioral.candidate_observations,
                    "delivered_observations": len(
                        behavioral.delivered_observations
                    ),
                    "omitted_relevant": behavioral.omitted_relevant_observations,
                    "omitted_critical": behavioral.omitted_critical_observations,
                    "sufficient": bool(behavioral.sufficient),
                    "within_behavior_budget": cap_ok,
                    "pattern_score": behavior_score,
                },
                "missing_identifier_control_ok": control_ok,
            }
        )

    symbol_recall = (
        float(symbol_matched) / float(total_required) if total_required else 1.0
    )
    behavior_recall = (
        float(behavior_matched) / float(total_required) if total_required else 1.0
    )
    gate = {
        "behavior_improves_aggregate_pattern_recall": behavior_matched > symbol_matched,
        "no_per_task_pattern_regression": no_task_regressions,
        "missing_identifier_control_ok": missing_control_ok,
        "all_behavior_packets_within_budget": behavior_caps_ok,
    }
    gate["pass"] = all(bool(value) for key, value in gate.items() if key != "pass")

    result = {
        "schema": "feynmap.p2_4b_fresh_behavior_result.v1",
        "status": "fresh_source_locked_first_replay",
        "frozen_manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "source_commit_before_oracle": manifest["source"]["source_commit_before_oracle"],
        "task_count": len(records),
        "answerable_task_count": sum(
            1 for task in manifest["tasks"] if task["expected_status"] == "answer"
        ),
        "required_behavior_patterns": total_required,
        "arms": {
            "symbol_evidence": {
                "matched_patterns": symbol_matched,
                "pattern_recall": round(symbol_recall, 6),
                "description": "P2.3a model-facing symbol_evidence context only",
            },
            "behavior_deterministic": {
                "matched_patterns": behavior_matched,
                "pattern_recall": round(behavior_recall, 6),
                "description": "same sparse context plus P2.4 deterministic grounded behavioral envelope",
            },
            "behavior_provider_optional": {
                "status": "not_run",
                "reason": "No real provider/model was explicitly configured for this first replay; no mock-provider result is presented as model evidence.",
            },
        },
        "fresh_representation_gate": gate,
        "default_product_policy_changed": false,
        "records": records,
        "limitations": manifest["limitations"],
    }
    if output is not None:
        Path(output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return result


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="experiments/p2_4b_behavior_manifest.json"
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = run_evaluation(
        Path(args.manifest), output=Path(args.output) if args.output else None
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "required_behavior_patterns": result["required_behavior_patterns"],
                "symbol_evidence": result["arms"]["symbol_evidence"],
                "behavior_deterministic": result["arms"]["behavior_deterministic"],
                "fresh_representation_gate": result["fresh_representation_gate"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
