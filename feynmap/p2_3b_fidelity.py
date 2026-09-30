"""P2.3b downstream-answer fidelity harness.

This stage separates three things that earlier P2 work intentionally did not
conflate: source/search/packing integrity, downstream model answers, and a
source-authored scoring oracle. Context packets never contain claim labels.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .context import estimate_tokens
from .context_pipeline import SparseContextPipeline
from .delivery_channels import DeliveryChannelPolicy
from .engine import FeynMapEngine
from .minimal_context import MinimalContextBudget
from .p1_replay_acceptance import git_blob_sha
from .p2_delivery_experiment import _graph_identity, source_path

MANIFEST_SCHEMA = "feynmap.p2_3b_answer_fidelity_manifest.v1"
EXPORT_SCHEMA = "feynmap.p2_3b_context_export.v1"
SCORE_SCHEMA = "feynmap.p2_3b_answer_fidelity_score.v1"
FROZEN_MANIFEST_GIT_BLOB = "d136168b47939af7ce8f9440cc9abd022b777310"


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    if git_blob_sha(raw) != FROZEN_MANIFEST_GIT_BLOB:
        raise ValueError("P2.3b answer/source oracle changed after pre-registration")
    value = json.loads(raw.decode("utf-8"))
    if value.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("P2.3b unexpected manifest schema")
    task_ids = [item.get("id") for item in value.get("tasks", [])]
    if task_ids != [
        "reserve-order-implementation",
        "reservation-regression-test",
        "priority-migration-answer",
        "cancel-policy-answer",
        "javascript-status-answer",
        "missing-refund-identifier",
    ]:
        raise ValueError("P2.3b frozen task identities/order changed")
    if [row.get("id") for row in value.get("arms", [])] != [
        "legacy", "symbol_evidence",
    ]:
        raise ValueError("P2.3b frozen arm identities changed")
    if [row.get("id") for row in value.get("budgets", [])] != [
        "tight", "standard",
    ]:
        raise ValueError("P2.3b frozen budgets changed")
    if value.get("model_answer_budget") != "standard":
        raise ValueError("P2.3b model-answer budget changed")
    return value


def _python_declarations(file: Path) -> Set[Tuple[str, ...]]:
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    names: Set[Tuple[str, ...]] = set()

    def visit(items: Sequence[Any], stack: Tuple[str, ...]) -> None:
        for item in items:
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                nested = stack + (item.name,)
                names.add(nested)
                visit(item.body, nested)
            else:
                for _, value in ast.iter_fields(item):
                    if isinstance(value, list):
                        visit(value, stack)
    visit(tree.body, ())
    return names


def _javascript_declarations(file: Path) -> Set[Tuple[str, ...]]:
    text = file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    )
    return {(match.group(1),) for match in pattern.finditer(text)}


def verify_source(manifest: Mapping[str, Any], root: Path) -> Dict[str, Set[Tuple[str, ...]]]:
    declarations: Dict[str, Set[Tuple[str, ...]]] = {}
    for relpath, expected in manifest["source"]["blobs"].items():
        file = root / relpath
        if not file.is_file():
            raise ValueError("P2.3b frozen source file missing: " + relpath)
        if git_blob_sha(file.read_bytes()) != expected:
            raise ValueError("P2.3b frozen source blob mismatch: " + relpath)
        if file.suffix == ".py":
            declarations[relpath] = _python_declarations(file)
        elif file.suffix in {".js", ".jsx", ".mjs"}:
            declarations[relpath] = _javascript_declarations(file)
        else:
            raise ValueError("P2.3b unsupported frozen source type: " + relpath)

    for task in manifest["tasks"]:
        for claim in task.get("required_claims", []):
            for label in claim.get("support_symbols", []):
                relpath, name = label["file"], label["name"]
                if relpath not in declarations:
                    raise ValueError(task["id"] + ": claim support file was not frozen")
                if not any(parts[-1] == name for parts in declarations[relpath]):
                    raise ValueError(
                        "%s: source-authored support symbol absent: %s:%s"
                        % (task["id"], relpath, name)
                    )
    return declarations


def _resolve_symbol(graph: Any, label: Mapping[str, str]) -> List[str]:
    return sorted(
        node.id for node in graph.nodes
        if source_path(node) == label["file"]
        and node.name == label["name"]
        and (
            not label.get("qualified_name")
            or node.qualified_name == label.get("qualified_name")
        )
    )


def _support_index(graph: Any, task: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for claim in task.get("required_claims", []):
        labels = []
        node_ids: Set[str] = set()
        for label in claim.get("support_symbols", []):
            matches = _resolve_symbol(graph, label)
            labels.append({"label": dict(label), "node_ids": matches})
            node_ids.update(matches)
        result[claim["id"]] = {
            "lexical_groups": claim["lexical_groups"],
            "support": labels,
            "support_node_ids": sorted(node_ids),
        }
    return result


def _budget(spec: Mapping[str, Any]) -> MinimalContextBudget:
    return MinimalContextBudget(
        max_tokens=int(spec["max_tokens"]),
        max_nodes=int(spec["max_nodes"]),
        max_edges=int(spec["max_edges"]),
    )


def _policy(spec: Mapping[str, Any]) -> Optional[DeliveryChannelPolicy]:
    value = spec.get("policy")
    return DeliveryChannelPolicy(**value) if value is not None else None


def export_contexts(manifest: Mapping[str, Any], root: Path, output: Path) -> Dict[str, Any]:
    declarations = verify_source(manifest, root)
    graph = FeynMapEngine().analyze(
        str(root),
        language=manifest["source"]["language"],
        framework=manifest["source"]["framework"],
    )
    if graph.diagnostics.get("errors"):
        raise ValueError("P2.3b graph validation errors: %r" % graph.diagnostics["errors"][:3])
    graph_identity = _graph_identity(graph)
    pipeline = SparseContextPipeline(graph)
    export_root = output
    inputs = export_root / "model_inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    model_budget_id = manifest["model_answer_budget"]

    for task in manifest["tasks"]:
        conf = manifest["activation"]
        activated = pipeline.search.concept(
            task["query"],
            seed_limit=conf["seed_limit"],
            candidate_limit=conf["candidate_limit"],
            max_depth=conf["max_depth"],
            beam_width=conf["beam_width"],
            max_nodes=conf["max_nodes"],
            direction=conf["direction"],
        ).search
        active_ids = {hit.node.id for hit in activated.hits}
        active_edge_ids = {
            edge.id for edge in activated.edges
            if edge.source in active_ids and edge.target in active_ids
        }
        support = _support_index(graph, task)
        for budget_spec in manifest["budgets"]:
            for arm in manifest["arms"]:
                context = pipeline.packer.pack(
                    activated,
                    budget=_budget(budget_spec),
                    delivery_policy=_policy(arm),
                )
                selected_nodes = set(context.selected_node_ids)
                selected_edges = set(context.selected_edge_ids)
                if not selected_nodes <= active_ids or not selected_edges <= active_edge_ids:
                    raise ValueError(task["id"] + ": packer escaped shared activation")
                edge_by_id = {edge.id: edge for edge in activated.edges}
                for edge_id in selected_edges:
                    edge = edge_by_id[edge_id]
                    if not {edge.source, edge.target} <= selected_nodes:
                        raise ValueError(task["id"] + ": delivered edge missing endpoint")
                if context.delivered_tokens != estimate_tokens(context.payload):
                    raise ValueError(task["id"] + ": delivered token estimate mismatch")
                packet_key = "%s|%s|%s" % (task["id"], budget_spec["id"], arm["id"])
                packet_id = hashlib.sha256(packet_key.encode("utf-8")).hexdigest()[:16]
                envelope = {
                    "schema": "feynmap.p2_3b_model_input.v1",
                    "packet_id": packet_id,
                    "question": task["query"],
                    "delivery_sufficient": bool(context.sufficient),
                    "unresolved_query_identifiers": list(
                        getattr(context, "unresolved_query_identifiers", ()) or ()
                    ),
                    "context": context.payload,
                    "answer_instruction": manifest["answer_protocol"]["instruction"],
                    "answer_schema": manifest["answer_protocol"]["schema"],
                }
                packet_sha = _sha256(envelope)
                model_visible = budget_spec["id"] == model_budget_id
                if model_visible:
                    (inputs / (packet_id + ".json")).write_text(
                        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    print("P2_3B_PACKET " + packet_id + " " + compact_json(envelope))
                records.append({
                    "packet_id": packet_id,
                    "packet_sha256": packet_sha,
                    "task_id": task["id"],
                    "arm": arm["id"],
                    "budget": budget_spec["id"],
                    "model_visible": model_visible,
                    "query": task["query"],
                    "expected_status": task["expected_status"],
                    "expected_missing_identifiers": task.get("expected_missing_identifiers", []),
                    "selected_node_ids": list(context.selected_node_ids),
                    "selected_edge_ids": list(context.selected_edge_ids),
                    "delivered_tokens_estimate": context.delivered_tokens,
                    "delivery_sufficient": bool(context.sufficient),
                    "unresolved_query_identifiers": list(
                        getattr(context, "unresolved_query_identifiers", ()) or ()
                    ),
                    "support_index": support,
                    "unsupported_traps": task.get("unsupported_traps", []),
                })
        if _graph_identity(graph) != graph_identity:
            raise ValueError(task["id"] + ": context export mutated graph truth")

    result = {
        "schema": EXPORT_SCHEMA,
        "manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "source_files_verified": len(declarations),
        "graph_identity_sha256": graph_identity,
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "model_answer_budget": model_budget_id,
        "task_count": len(manifest["tasks"]),
        "records": records,
        "gold_present_only_in_index_not_model_inputs": True,
        "default_policy_changed": False,
    }
    (export_root / "index.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _claim_text_matches(text: str, groups: Sequence[Sequence[str]]) -> bool:
    normalized = text.casefold()
    return all(any(term.casefold() in normalized for term in group) for group in groups)


def _trap_matches(text: str, traps: Sequence[Mapping[str, Any]]) -> List[str]:
    normalized = text.casefold()
    found = []
    for trap in traps:
        if any(phrase.casefold() in normalized for phrase in trap.get("any_phrases", [])):
            found.append(trap["id"])
    return found


def _load_answer(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") not in {"answer", "need_more_context"}:
        raise ValueError(path.name + ": invalid answer status")
    if not isinstance(value.get("claims", []), list):
        raise ValueError(path.name + ": claims must be a list")
    if not isinstance(value.get("missing_identifiers", []), list):
        raise ValueError(path.name + ": missing_identifiers must be a list")
    return value


def score_answers(
    manifest: Mapping[str, Any], index: Mapping[str, Any], answers_dir: Path,
) -> Dict[str, Any]:
    if index.get("schema") != EXPORT_SCHEMA:
        raise ValueError("P2.3b invalid context export schema")
    if index.get("manifest_git_blob") != FROZEN_MANIFEST_GIT_BLOB:
        raise ValueError("P2.3b context index references wrong oracle")
    run_path = answers_dir / "run.json"
    if not run_path.is_file():
        raise ValueError("P2.3b answer run metadata is missing")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("schema") != "feynmap.p2_3b_model_run.v1":
        raise ValueError("P2.3b invalid model run metadata")

    records = [row for row in index["records"] if row["model_visible"]]
    if len(records) != len(manifest["tasks"]) * len(manifest["arms"]):
        raise ValueError("P2.3b standard model packet count changed")
    details = []
    for record in records:
        answer_path = answers_dir / (record["packet_id"] + ".json")
        if not answer_path.is_file():
            raise ValueError("P2.3b missing answer: " + record["packet_id"])
        answer = _load_answer(answer_path)
        selected_nodes = set(record["selected_node_ids"])
        selected_edges = set(record["selected_edge_ids"])
        claims = answer.get("claims", [])
        invalid_citations = []
        uncited_claims = []
        trap_hits: Set[str] = set()
        for position, claim in enumerate(claims):
            text = str(claim.get("text", ""))
            node_refs = set(str(item) for item in claim.get("evidence_nodes", []))
            edge_refs = set(str(item) for item in claim.get("evidence_edges", []))
            if not node_refs and not edge_refs:
                uncited_claims.append(position)
            if not node_refs <= selected_nodes or not edge_refs <= selected_edges:
                invalid_citations.append(position)
            trap_hits.update(_trap_matches(text, record["unsupported_traps"]))

        matched_required = []
        for claim_id, oracle in record["support_index"].items():
            supported = set(oracle["support_node_ids"])
            for claim in claims:
                text = str(claim.get("text", ""))
                cited = set(str(item) for item in claim.get("evidence_nodes", []))
                if _claim_text_matches(text, oracle["lexical_groups"]) and cited.intersection(supported):
                    matched_required.append(claim_id)
                    break

        expected_status = record["expected_status"]
        missing = set(str(item) for item in answer.get("missing_identifiers", []))
        expected_missing = set(record.get("expected_missing_identifiers", []))
        status_ok = answer["status"] == expected_status
        missing_ok = (
            expected_status != "need_more_context"
            or expected_missing <= missing
        )
        no_factual_answer_when_unresolved = not (
            expected_status == "need_more_context" and claims
        )
        required_total = len(record["support_index"])
        required_recall = (
            float(len(set(matched_required))) / required_total
            if required_total else 1.0
        )
        citations_valid = not invalid_citations and not uncited_claims
        task_passed = (
            status_ok and missing_ok and no_factual_answer_when_unresolved
            and required_recall == 1.0 and not trap_hits and citations_valid
        )
        details.append({
            "packet_id": record["packet_id"],
            "task_id": record["task_id"],
            "arm": record["arm"],
            "budget": record["budget"],
            "expected_status": expected_status,
            "answer_status": answer["status"],
            "status_ok": status_ok,
            "missing_identifier_behavior_ok": missing_ok,
            "no_factual_answer_when_unresolved": no_factual_answer_when_unresolved,
            "required_claims": required_total,
            "matched_required_claim_ids": sorted(set(matched_required)),
            "required_claim_recall": round(required_recall, 6),
            "claim_count": len(claims),
            "invalid_citation_claim_positions": invalid_citations,
            "uncited_claim_positions": uncited_claims,
            "unsupported_trap_hits": sorted(trap_hits),
            "citations_valid": citations_valid,
            "context_estimated_tokens": record["delivered_tokens_estimate"],
            "delivery_sufficient": record["delivery_sufficient"],
            "unresolved_query_identifiers": record["unresolved_query_identifiers"],
            "task_passed": task_passed,
        })

    summaries = []
    for arm in [item["id"] for item in manifest["arms"]]:
        rows = [row for row in details if row["arm"] == arm]
        answerable = [row for row in rows if row["expected_status"] == "answer"]
        unresolved = [row for row in rows if row["expected_status"] == "need_more_context"]
        required_total = sum(row["required_claims"] for row in answerable)
        matched_total = sum(len(row["matched_required_claim_ids"]) for row in answerable)
        usage = (run.get("usage_by_packet") or {})
        usage_rows = [usage.get(row["packet_id"]) for row in rows]
        provider_tokens_complete = all(
            isinstance(item, Mapping)
            and item.get("input_tokens") is not None
            and item.get("output_tokens") is not None
            for item in usage_rows
        )
        summaries.append({
            "arm": arm,
            "tasks": len(rows),
            "answerable_tasks": len(answerable),
            "answerable_task_passes": sum(row["task_passed"] for row in answerable),
            "required_claims": required_total,
            "matched_required_claims": matched_total,
            "required_claim_recall": (
                round(float(matched_total) / required_total, 6)
                if required_total else 1.0
            ),
            "unsupported_trap_hits": sum(len(row["unsupported_trap_hits"]) for row in rows),
            "invalid_or_uncited_claims": sum(
                len(row["invalid_citation_claim_positions"])
                + len(row["uncited_claim_positions"])
                for row in rows
            ),
            "correct_request_more_context_tasks": sum(
                row["task_passed"] for row in unresolved
            ),
            "request_more_context_tasks": len(unresolved),
            "context_estimated_tokens_sum": sum(row["context_estimated_tokens"] for row in rows),
            "mean_context_estimated_tokens": round(
                sum(row["context_estimated_tokens"] for row in rows) / len(rows), 2
            ),
            "provider_usage_complete": provider_tokens_complete,
            "provider_input_tokens_sum": (
                sum(int(item["input_tokens"]) for item in usage_rows)
                if provider_tokens_complete else None
            ),
            "provider_output_tokens_sum": (
                sum(int(item["output_tokens"]) for item in usage_rows)
                if provider_tokens_complete else None
            ),
        })

    by_arm = {row["arm"]: row for row in summaries}
    legacy = by_arm["legacy"]
    symbol = by_arm["symbol_evidence"]
    metric_gate = (
        symbol["required_claim_recall"] >= legacy["required_claim_recall"]
        and symbol["unsupported_trap_hits"] <= legacy["unsupported_trap_hits"]
        and symbol["invalid_or_uncited_claims"] <= legacy["invalid_or_uncited_claims"]
        and symbol["correct_request_more_context_tasks"] == symbol["request_more_context_tasks"]
        and symbol["context_estimated_tokens_sum"] <= legacy["context_estimated_tokens_sum"]
    )
    eligible = bool(run.get("eligible_for_shipping_decision"))
    if metric_gate and eligible:
        decision = "eligible_to_promote_symbol_evidence_default_subject_to_full_regression_ci"
    elif metric_gate:
        decision = "keep_opt_in_model_run_not_eligible_for_shipping_decision"
    else:
        decision = "keep_opt_in_downstream_fidelity_gate_not_met"

    result = {
        "schema": SCORE_SCHEMA,
        "manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "model_run": run,
        "details": details,
        "summaries": summaries,
        "metric_gate_passed": metric_gate,
        "shipping_decision": decision,
        "default_policy_changed": False,
        "limitations": manifest["limitations"] + [
            "Unsupported-claim count covers invalid/missing citations plus pre-registered trap patterns; it is not exhaustive semantic fact checking.",
            "An interactive run authored by a model that has seen the fixture/oracle must set eligible_for_shipping_decision=false.",
        ],
    }
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--manifest", required=True)
    export.add_argument("--project-root", required=True)
    export.add_argument("--output-dir", required=True)
    score = sub.add_parser("score")
    score.add_argument("--manifest", required=True)
    score.add_argument("--index", required=True)
    score.add_argument("--answers-dir", required=True)
    score.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest = load_manifest(Path(args.manifest))
    if args.command == "export":
        result = export_contexts(
            manifest, Path(args.project_root).resolve(), Path(args.output_dir)
        )
        print(compact_json({
            "status": "exported",
            "tasks": result["task_count"],
            "model_packets": sum(row["model_visible"] for row in result["records"]),
            "graph_nodes": result["graph_nodes"],
            "graph_edges": result["graph_edges"],
        }))
        return 0
    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    result = score_answers(manifest, index, Path(args.answers_dir))
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(compact_json({
        "status": "scored",
        "shipping_decision": result["shipping_decision"],
        "summaries": result["summaries"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
