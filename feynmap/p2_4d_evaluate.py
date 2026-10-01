"""P2.4d fresh downstream validation for repaired task-conditioned evidence.

The rollout fixture and scoring oracle are frozen before this module exists.
Context construction reads only task identifiers and natural-language queries.
Gold behavior patterns, required claims, support symbols, traps, and expected
statuses are touched only after both arms have produced model-facing packets.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .behavioral_context import BehaviorEvidenceBudget
from .context import estimate_tokens
from .context_pipeline import SparseContextPipeline
from .delivery_channels import DeliveryChannelPolicy
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .p2_delivery_experiment import _graph_identity, source_path
from .relevance import DeterministicRelevanceJudge
from .task_evidence import TaskConditionedEvidencePipeline


MANIFEST_SCHEMA = "feynmap.p2_4d_downstream_manifest.v1"
EXPORT_SCHEMA = "feynmap.p2_4d_context_export.v1"
MODEL_INPUT_SCHEMA = "feynmap.p2_4d_model_input.v1"
SCORE_SCHEMA = "feynmap.p2_4d_downstream_score.v1"
FROZEN_MANIFEST_GIT_BLOB = "153bd1d1e0912c6b008ac8b0ba00c76c3529662e"


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def git_blob_sha(path: Path) -> str:
    raw = Path(path).read_bytes()
    header = ("blob %d\0" % len(raw)).encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _sha256(value: Any) -> str:
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> Dict[str, Any]:
    path = Path(path)
    actual = git_blob_sha(path)
    if actual != FROZEN_MANIFEST_GIT_BLOB:
        raise ValueError(
            "P2.4d oracle changed after freeze: expected %s got %s"
            % (FROZEN_MANIFEST_GIT_BLOB, actual)
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unexpected P2.4d manifest schema")
    task_ids = [item.get("id") for item in value.get("tasks", [])]
    expected = [
        "deploy-batch-implementation",
        "oversized-batch-regression",
        "exact-batch-regression",
        "rollback-delegation",
        "health-window-migration",
        "javascript-rollout-label",
        "invalid-batch-size",
        "missing-force-promote",
    ]
    if task_ids != expected:
        raise ValueError("P2.4d frozen task identities/order changed")
    if [item.get("id") for item in value.get("arms", [])] != [
        "symbol_evidence", "behavior_repaired"
    ]:
        raise ValueError("P2.4d frozen arm identities changed")
    return value


def verify_source_blobs(manifest: Mapping[str, Any], project_root: Path) -> None:
    for relative, expected_sha in sorted(manifest["source"]["blobs"].items()):
        path = project_root / relative
        if not path.is_file():
            raise ValueError("P2.4d frozen source missing: " + relative)
        actual = git_blob_sha(path)
        if actual != expected_sha:
            raise ValueError(
                "P2.4d source changed after freeze: %s expected %s got %s"
                % (relative, expected_sha, actual)
            )


def _python_declarations(file: Path) -> Set[str]:
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    result: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            result.add(node.name)
    return result


def _javascript_declarations(file: Path) -> Set[str]:
    text = file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
    )
    return {match.group(1) for match in pattern.finditer(text)}


def verify_oracle_support_after_build(
    manifest: Mapping[str, Any], project_root: Path
) -> None:
    declarations: Dict[str, Set[str]] = {}
    for relative in manifest["source"]["blobs"]:
        file = project_root / relative
        if file.suffix == ".py":
            declarations[relative] = _python_declarations(file)
        elif file.suffix in {".js", ".jsx", ".mjs"}:
            declarations[relative] = _javascript_declarations(file)
        else:
            declarations[relative] = set()
    for task in manifest["tasks"]:
        for claim in task.get("required_claims", []):
            for label in claim.get("support_symbols", []):
                relpath = str(label["file"])
                name = str(label["name"])
                if name not in declarations.get(relpath, set()):
                    raise ValueError(
                        "%s: frozen support symbol absent: %s:%s"
                        % (task["id"], relpath, name)
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
        rows.append({"id": pattern["id"], "matched": bool(matched)})
    return {
        "required": len(rows),
        "matched": sum(1 for row in rows if row["matched"]),
        "patterns": rows,
    }


def _context_budget(spec: Mapping[str, Any]) -> MinimalContextBudget:
    return MinimalContextBudget(
        max_tokens=int(spec["max_tokens"]),
        max_nodes=int(spec["max_nodes"]),
        max_edges=int(spec["max_edges"]),
    )


def _behavior_budget(spec: Mapping[str, Any]) -> BehaviorEvidenceBudget:
    return BehaviorEvidenceBudget(
        max_tokens=int(spec["max_tokens"]),
        max_observations=int(spec["max_observations"]),
        max_source_chars=int(spec["max_source_chars"]),
    )


def _activation_identity(sparse: Any) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    search = sparse.activation.search
    return (
        tuple(hit.node.id for hit in search.hits),
        tuple(edge.id for edge in search.edges),
        tuple(node.id for node in search.roots),
    )


def _resolve_symbol(graph: Any, label: Mapping[str, str]) -> List[str]:
    return sorted(
        node.id
        for node in graph.nodes
        if source_path(node) == label["file"] and node.name == label["name"]
    )


def _support_index(
    graph: Any,
    task: Mapping[str, Any],
    *,
    selected_nodes: Sequence[str],
    selected_edges: Sequence[str],
    observations: Sequence[Any],
) -> Dict[str, Any]:
    selected_node_ids = set(selected_nodes)
    selected_edge_ids = set(selected_edges)
    edge_by_id = {edge.id: edge for edge in graph.edges}
    observation_by_symbol: Dict[str, List[str]] = {}
    for observation in observations:
        observation_by_symbol.setdefault(observation.symbol_id, []).append(observation.id)

    result: Dict[str, Any] = {}
    for claim in task.get("required_claims", []):
        support_nodes: Set[str] = set()
        labels = []
        for label in claim.get("support_symbols", []):
            matches = _resolve_symbol(graph, label)
            labels.append({"label": dict(label), "node_ids": matches})
            support_nodes.update(matches)

        refs: Set[str] = set()
        refs.update(support_nodes & selected_node_ids)
        for node_id in support_nodes:
            refs.update(observation_by_symbol.get(node_id, ()))
        for edge_id in selected_edge_ids:
            edge = edge_by_id.get(edge_id)
            if edge is not None and edge.source in support_nodes and edge.target in support_nodes:
                refs.add(edge_id)
        result[str(claim["id"])] = {
            "alternatives": claim.get("alternatives", []),
            "support": labels,
            "support_node_ids": sorted(support_nodes),
            "support_refs": sorted(refs),
        }
    return result


def _evidence_refs(
    selected_nodes: Sequence[str],
    selected_edges: Sequence[str],
    observations: Sequence[Any],
) -> Dict[str, List[str]]:
    return {
        "nodes": list(selected_nodes),
        "edges": list(selected_edges),
        "observations": [item.id for item in observations],
    }


def _all_refs(refs: Mapping[str, Sequence[str]]) -> Set[str]:
    result: Set[str] = set()
    for values in refs.values():
        result.update(str(item) for item in values)
    return result


def _packet(
    packet_id: str,
    question: str,
    context: Mapping[str, Any],
    *,
    sufficient: bool,
    unresolved: Sequence[str],
    refs: Mapping[str, Sequence[str]],
    answer_contract: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema": MODEL_INPUT_SCHEMA,
        "packet_id": packet_id,
        "question": question,
        "delivery_sufficient": bool(sufficient),
        "unresolved_query_identifiers": list(unresolved),
        "context": context,
        "evidence_refs": {key: list(value) for key, value in refs.items()},
        "answer_instruction": " ".join(str(item) for item in answer_contract["rules"]),
        "answer_schema": answer_contract["shape"],
    }


def export_contexts(
    manifest_path: Path,
    *,
    output: Optional[Path] = None,
) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    repo_root = manifest_path.parent.parent
    project_root = (repo_root / manifest["source"]["root"]).resolve()
    verify_source_blobs(manifest, project_root)

    graph = FeynMapEngine().analyze(
        str(project_root),
        language=str(manifest["source"]["language"]),
        framework=str(manifest["source"]["framework"]),
    )
    if graph.diagnostics.get("errors"):
        raise ValueError("P2.4d graph errors: %r" % graph.diagnostics["errors"][:3])
    graph_identity = _graph_identity(graph)

    context_budget = _context_budget(manifest["context_budget"])
    behavior_budget = _behavior_budget(manifest["behavior_budget"])
    activation = manifest["activation"]

    symbol_pipeline = SparseContextPipeline(graph)
    delivery_policy = DeliveryChannelPolicy(mode="symbol_evidence")
    repaired_pipeline = TaskConditionedEvidencePipeline(
        graph,
        project_root,
        relevance_judge=DeterministicRelevanceJudge(),
        behavior_budget=behavior_budget,
    )

    # First pass: construct every context and model packet from task id + query only.
    built: Dict[str, Dict[str, Any]] = {}
    for task in manifest["tasks"]:
        task_id = str(task["id"])
        query = str(task["query"])
        symbol = symbol_pipeline.concept(
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
        repaired = repaired_pipeline.concept(
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
        if _activation_identity(symbol) != _activation_identity(repaired.sparse):
            raise ValueError(task_id + ": arms did not share exact activation")
        active_ids = {hit.node.id for hit in symbol.activation.search.hits}
        if not set(repaired.sparse.context.selected_node_ids) <= active_ids:
            raise ValueError(task_id + ": repaired continuation escaped activation")
        if len(repaired.continuation.added_node_ids) > 1:
            raise ValueError(task_id + ": repaired continuation exceeded one-node contract")
        if repaired.behavioral.behavior_tokens > behavior_budget.max_tokens:
            raise ValueError(task_id + ": repaired behavioral packet exceeded cap")

        built[task_id] = {
            "query": query,
            "symbol": symbol,
            "repaired": repaired,
        }
        if _graph_identity(graph) != graph_identity:
            raise ValueError(task_id + ": context construction mutated graph truth")

    # Gold/source-support validation starts only after all model-facing contexts exist.
    verify_oracle_support_after_build(manifest, project_root)

    model_inputs: Optional[Path] = None
    if output is not None:
        output = Path(output)
        model_inputs = output / "model_inputs"
        model_inputs.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []
    total_required = 0
    symbol_matched = 0
    repaired_matched = 0
    no_task_regressions = True
    all_caps_ok = True
    missing_control_ok = True
    continuation_contract_ok = True

    for task in manifest["tasks"]:
        task_id = str(task["id"])
        row = built[task_id]
        symbol = row["symbol"]
        repaired = row["repaired"]
        symbol_score = _score_patterns(task, symbol.context.payload)
        repaired_score = _score_patterns(task, repaired.behavioral.payload)
        total_required += int(symbol_score["required"])
        symbol_matched += int(symbol_score["matched"])
        repaired_matched += int(repaired_score["matched"])
        if repaired_score["matched"] < symbol_score["matched"]:
            no_task_regressions = False

        cap_ok = repaired.behavioral.behavior_tokens <= behavior_budget.max_tokens
        all_caps_ok = all_caps_ok and cap_ok
        active_ids = {hit.node.id for hit in symbol.activation.search.hits}
        continuation_ok = (
            len(repaired.continuation.added_node_ids) <= 1
            and set(repaired.continuation.added_node_ids) <= active_ids
        )
        continuation_contract_ok = continuation_contract_ok and continuation_ok

        expected_missing = list(task.get("expected_missing_identifiers", []))
        control_ok = True
        if expected_missing:
            unresolved = list(repaired.sparse.context.unresolved_query_identifiers)
            observation_text = "\n".join(
                "%s\n%s" % (item.summary, item.source or "")
                for item in repaired.behavioral.delivered_observations
            ).casefold()
            control_ok = (
                all(identifier in unresolved for identifier in expected_missing)
                and not repaired.behavioral.sufficient
                and all(identifier.casefold() not in observation_text for identifier in expected_missing)
            )
            missing_control_ok = missing_control_ok and control_ok

        arm_rows = []
        for arm_id in ("symbol_evidence", "behavior_repaired"):
            if arm_id == "symbol_evidence":
                context = symbol.context
                payload = context.payload
                selected_nodes = list(context.selected_node_ids)
                selected_edges = list(context.selected_edge_ids)
                observations: Sequence[Any] = ()
                sufficient = bool(context.sufficient)
                unresolved = list(context.unresolved_query_identifiers)
                tokens = int(context.delivered_tokens)
                behavior_tokens = None
                continuation = None
            else:
                context = repaired.sparse.context
                payload = repaired.behavioral.payload
                selected_nodes = list(context.selected_node_ids)
                selected_edges = list(context.selected_edge_ids)
                observations = tuple(repaired.behavioral.delivered_observations)
                sufficient = bool(repaired.behavioral.sufficient)
                unresolved = list(context.unresolved_query_identifiers)
                tokens = int(repaired.behavioral.total_tokens)
                behavior_tokens = int(repaired.behavioral.behavior_tokens)
                continuation = repaired.continuation.to_dict()

            refs = _evidence_refs(selected_nodes, selected_edges, observations)
            key = "%s|%s|%s" % (FROZEN_MANIFEST_GIT_BLOB, task_id, arm_id)
            packet_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            envelope = _packet(
                packet_id,
                row["query"],
                payload,
                sufficient=sufficient,
                unresolved=unresolved,
                refs=refs,
                answer_contract=manifest["answer_contract"],
            )
            if "arm" in envelope or "expected_status" in envelope:
                raise ValueError(task_id + ": model packet leaked scorer metadata")
            if estimate_tokens(payload) != (
                symbol.context.delivered_tokens
                if arm_id == "symbol_evidence"
                else repaired.behavioral.total_tokens
            ):
                raise ValueError(task_id + ": context token estimate mismatch")

            support = _support_index(
                graph,
                task,
                selected_nodes=selected_nodes,
                selected_edges=selected_edges,
                observations=observations,
            )
            record = {
                "packet_id": packet_id,
                "packet_sha256": _sha256(envelope),
                "task_id": task_id,
                "arm": arm_id,
                "query": row["query"],
                "expected_status": task["expected_status"],
                "expected_missing_identifiers": task.get("expected_missing_identifiers", []),
                "selected_node_ids": selected_nodes,
                "selected_edge_ids": selected_edges,
                "observation_ids": [item.id for item in observations],
                "allowed_evidence_refs": sorted(_all_refs(refs)),
                "delivered_tokens_estimate": tokens,
                "behavior_tokens_estimate": behavior_tokens,
                "delivery_sufficient": sufficient,
                "unresolved_query_identifiers": unresolved,
                "support_index": support,
                "unsupported_traps": list(task.get("unsupported_traps", [])),
                "continuation": continuation,
            }
            records.append(record)
            arm_rows.append(record)
            if model_inputs is not None:
                (model_inputs / (packet_id + ".json")).write_text(
                    json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

        if len(arm_rows) != 2:
            raise ValueError(task_id + ": expected exactly two model packets")

    symbol_recall = float(symbol_matched) / float(total_required) if total_required else 1.0
    repaired_recall = float(repaired_matched) / float(total_required) if total_required else 1.0
    representation_gate = {
        "behavior_repaired_recall_at_least_0_85": repaired_recall >= 0.85,
        "no_per_task_pattern_regression": no_task_regressions,
        "missing_identifier_control_ok": missing_control_ok,
        "all_behavior_packets_within_budget": all_caps_ok,
        "continuation_contract_ok": continuation_contract_ok,
    }
    representation_gate["pass"] = all(
        bool(value)
        for key, value in representation_gate.items()
        if key != "pass"
    )

    result = {
        "schema": EXPORT_SCHEMA,
        "status": "fresh_source_locked_context_export",
        "manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "source_commit_before_oracle": manifest["source"]["source_commit_before_oracle"],
        "graph_identity_sha256": graph_identity,
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "task_count": len(manifest["tasks"]),
        "answerable_task_count": sum(
            1 for task in manifest["tasks"] if task["expected_status"] == "answer"
        ),
        "required_behavior_patterns": total_required,
        "representation": {
            "symbol_evidence": {
                "matched_patterns": symbol_matched,
                "pattern_recall": round(symbol_recall, 6),
            },
            "behavior_repaired": {
                "matched_patterns": repaired_matched,
                "pattern_recall": round(repaired_recall, 6),
            },
        },
        "fresh_representation_gate": representation_gate,
        "records": records,
        "gold_present_only_in_index_not_model_inputs": True,
        "default_product_policy_changed": False,
        "limitations": manifest["limitations"],
    }

    if output is not None:
        Path(output).mkdir(parents=True, exist_ok=True)
        (Path(output) / "index.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        representation = {
            key: result[key]
            for key in (
                "schema",
                "status",
                "manifest_git_blob",
                "source_commit_before_oracle",
                "task_count",
                "answerable_task_count",
                "required_behavior_patterns",
                "representation",
                "fresh_representation_gate",
                "default_product_policy_changed",
                "limitations",
            )
        }
        (Path(output) / "representation.json").write_text(
            json.dumps(representation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def _load_answer(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") not in {"answer", "need_more_context"}:
        raise ValueError(path.name + ": invalid answer status")
    if not isinstance(value.get("claims", []), list):
        raise ValueError(path.name + ": claims must be a list")
    if not isinstance(value.get("missing_identifiers", []), list):
        raise ValueError(path.name + ": missing_identifiers must be a list")
    for claim in value.get("claims", []):
        if not isinstance(claim, Mapping):
            raise ValueError(path.name + ": claim must be an object")
        if not isinstance(claim.get("evidence_refs", []), list):
            raise ValueError(path.name + ": evidence_refs must be a list")
    return value


def _claim_matches(text: str, alternatives: Sequence[Sequence[str]]) -> bool:
    normalized = str(text).casefold()
    return any(
        all(str(phrase).casefold() in normalized for phrase in alternative)
        for alternative in alternatives
    )


def _trap_hits(text: str, traps: Sequence[str]) -> List[str]:
    normalized = str(text).casefold()
    return sorted(
        trap for trap in traps if str(trap).casefold() in normalized
    )


def score_answers(
    manifest_path: Path,
    index_path: Path,
    answers_dir: Path,
    *,
    output: Optional[Path] = None,
) -> Dict[str, Any]:
    manifest = load_manifest(Path(manifest_path))
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    if index.get("schema") != EXPORT_SCHEMA:
        raise ValueError("P2.4d invalid context export schema")
    if index.get("manifest_git_blob") != FROZEN_MANIFEST_GIT_BLOB:
        raise ValueError("P2.4d context export references wrong oracle")

    answers_dir = Path(answers_dir)
    run_path = answers_dir / "run.json"
    if not run_path.is_file():
        raise ValueError("P2.4d answer run metadata missing")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("schema") != "feynmap.p2_4d_model_run.v1":
        raise ValueError("P2.4d invalid model run schema")
    oracle_exposure = bool(run.get("oracle_exposure", False))
    eligible = bool(run.get("eligible_for_shipping_decision", False))
    if oracle_exposure and eligible:
        raise ValueError("oracle-exposed answer run cannot be shipping-eligible")

    task_by_id = {str(task["id"]): task for task in manifest["tasks"]}
    details: List[Dict[str, Any]] = []
    arm_totals: Dict[str, Dict[str, Any]] = {
        "symbol_evidence": {
            "required_claims": 0,
            "matched_claims": 0,
            "grounded_claims": 0,
            "answerable_tasks": 0,
            "answerable_task_passes": 0,
            "unsupported_trap_hits": 0,
            "invalid_citations": 0,
            "uncited_claims": 0,
            "missing_context_tasks": 0,
            "correct_missing_context": 0,
        },
        "behavior_repaired": {
            "required_claims": 0,
            "matched_claims": 0,
            "grounded_claims": 0,
            "answerable_tasks": 0,
            "answerable_task_passes": 0,
            "unsupported_trap_hits": 0,
            "invalid_citations": 0,
            "uncited_claims": 0,
            "missing_context_tasks": 0,
            "correct_missing_context": 0,
        },
    }

    for record in index["records"]:
        task = task_by_id[record["task_id"]]
        answer_path = answers_dir / (record["packet_id"] + ".json")
        if not answer_path.is_file():
            raise ValueError("P2.4d missing answer: " + record["packet_id"])
        answer = _load_answer(answer_path)
        allowed = set(str(item) for item in record["allowed_evidence_refs"])

        invalid_citations: List[int] = []
        uncited_claims: List[int] = []
        traps: Set[str] = set()
        answer_claims = answer.get("claims", [])
        for position, claim in enumerate(answer_claims):
            text = str(claim.get("text", ""))
            refs = set(str(item) for item in claim.get("evidence_refs", []))
            if not refs:
                uncited_claims.append(position)
            if not refs <= allowed:
                invalid_citations.append(position)
            traps.update(_trap_hits(text, record["unsupported_traps"]))

        required_rows = []
        grounded_count = 0
        for required in task.get("required_claims", []):
            oracle = record["support_index"][required["id"]]
            support_refs = set(str(item) for item in oracle["support_refs"])
            matched_positions = []
            grounded_positions = []
            for position, claim in enumerate(answer_claims):
                text = str(claim.get("text", ""))
                if _claim_matches(text, required.get("alternatives", [])):
                    matched_positions.append(position)
                    cited = set(str(item) for item in claim.get("evidence_refs", []))
                    if cited & support_refs:
                        grounded_positions.append(position)
            matched = bool(matched_positions)
            grounded = bool(grounded_positions)
            if grounded:
                grounded_count += 1
            required_rows.append(
                {
                    "id": required["id"],
                    "matched": matched,
                    "grounded": grounded,
                    "matched_claim_positions": matched_positions,
                    "grounded_claim_positions": grounded_positions,
                }
            )

        expected_status = str(task["expected_status"])
        if expected_status == "answer":
            task_pass = (
                answer.get("status") == "answer"
                and all(row["matched"] and row["grounded"] for row in required_rows)
                and not traps
                and not invalid_citations
                and not uncited_claims
            )
            missing_ok = None
        else:
            expected_missing = set(
                str(item) for item in task.get("expected_missing_identifiers", [])
            )
            actual_missing = set(
                str(item) for item in answer.get("missing_identifiers", [])
            )
            missing_ok = (
                answer.get("status") == "need_more_context"
                and expected_missing <= actual_missing
                and not traps
                and not invalid_citations
                and not answer_claims
            )
            task_pass = bool(missing_ok)

        arm = str(record["arm"])
        totals = arm_totals[arm]
        totals["required_claims"] += len(required_rows)
        totals["matched_claims"] += sum(1 for row in required_rows if row["matched"])
        totals["grounded_claims"] += grounded_count
        totals["unsupported_trap_hits"] += len(traps)
        totals["invalid_citations"] += len(invalid_citations)
        totals["uncited_claims"] += len(uncited_claims)
        if expected_status == "answer":
            totals["answerable_tasks"] += 1
            totals["answerable_task_passes"] += int(bool(task_pass))
        else:
            totals["missing_context_tasks"] += 1
            totals["correct_missing_context"] += int(bool(missing_ok))

        details.append(
            {
                "packet_id": record["packet_id"],
                "task_id": record["task_id"],
                "arm": arm,
                "answer_status": answer.get("status"),
                "required_claims": required_rows,
                "trap_hits": sorted(traps),
                "invalid_citation_claim_positions": invalid_citations,
                "uncited_claim_positions": uncited_claims,
                "missing_context_ok": missing_ok,
                "task_pass": bool(task_pass),
            }
        )

    for arm, totals in arm_totals.items():
        required = int(totals["required_claims"])
        grounded = int(totals["grounded_claims"])
        matched = int(totals["matched_claims"])
        answerable = int(totals["answerable_tasks"])
        totals["required_claim_recall"] = round(
            float(matched) / float(required) if required else 1.0, 6
        )
        totals["grounded_required_claim_recall"] = round(
            float(grounded) / float(required) if required else 1.0, 6
        )
        totals["answerable_task_pass_rate"] = round(
            float(totals["answerable_task_passes"]) / float(answerable)
            if answerable else 1.0,
            6,
        )

    symbol = arm_totals["symbol_evidence"]
    repaired = arm_totals["behavior_repaired"]
    comparative = {
        "eligible_blind_run": bool(eligible and not oracle_exposure),
        "repaired_claim_recall_exceeds_symbol": (
            repaired["required_claim_recall"] > symbol["required_claim_recall"]
        ),
        "repaired_task_passes_not_lower": (
            repaired["answerable_task_passes"] >= symbol["answerable_task_passes"]
        ),
        "repaired_traps_not_higher": (
            repaired["unsupported_trap_hits"] <= symbol["unsupported_trap_hits"]
        ),
        "repaired_invalid_citations_not_higher": (
            repaired["invalid_citations"] <= symbol["invalid_citations"]
        ),
        "missing_context_control_ok": (
            repaired["correct_missing_context"] == repaired["missing_context_tasks"] == 1
        ),
    }
    comparative["pass"] = all(
        bool(value)
        for key, value in comparative.items()
        if key != "pass"
    )
    absolute = {
        "eligible_for_shipping_decision": bool(eligible and not oracle_exposure),
        "claim_recall_at_least_0_90": repaired["required_claim_recall"] >= 0.90,
        "at_least_6_of_7_answerable_tasks_pass": repaired["answerable_task_passes"] >= 6,
        "zero_unsupported_traps": repaired["unsupported_trap_hits"] == 0,
        "zero_invalid_or_uncited_claims": (
            repaired["invalid_citations"] == 0 and repaired["uncited_claims"] == 0
        ),
        "missing_context_control_ok": (
            repaired["correct_missing_context"] == repaired["missing_context_tasks"] == 1
        ),
    }
    absolute["pass"] = all(
        bool(value)
        for key, value in absolute.items()
        if key != "pass"
    )

    result = {
        "schema": SCORE_SCHEMA,
        "manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "model_run": run,
        "oracle_blind": not oracle_exposure,
        "eligible_for_shipping_decision": bool(eligible and not oracle_exposure),
        "arms": arm_totals,
        "blind_downstream_comparative_gate": comparative,
        "absolute_fidelity_guard": absolute,
        "default_product_policy_changed": bool(absolute["pass"]),
        "details": details,
    }
    if output is not None:
        Path(output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export")
    export.add_argument(
        "--manifest", default="experiments/p2_4d_downstream_manifest.json"
    )
    export.add_argument("--output", required=True)

    score = sub.add_parser("score")
    score.add_argument(
        "--manifest", default="experiments/p2_4d_downstream_manifest.json"
    )
    score.add_argument("--index", required=True)
    score.add_argument("--answers", required=True)
    score.add_argument("--output")

    args = parser.parse_args(argv)
    if args.command == "export":
        result = export_contexts(Path(args.manifest), output=Path(args.output))
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "required_behavior_patterns": result["required_behavior_patterns"],
                    "representation": result["representation"],
                    "fresh_representation_gate": result["fresh_representation_gate"],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "score":
        result = score_answers(
            Path(args.manifest),
            Path(args.index),
            Path(args.answers),
            output=Path(args.output) if args.output else None,
        )
        print(
            json.dumps(
                {
                    "arms": result["arms"],
                    "blind_downstream_comparative_gate": result[
                        "blind_downstream_comparative_gate"
                    ],
                    "absolute_fidelity_guard": result["absolute_fidelity_guard"],
                },
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
