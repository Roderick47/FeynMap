"""P2.3b: sealed downstream context packets and conservative answer scoring."""
import copy
import json
from pathlib import Path
from shutil import copytree

import pytest

from feynmap.p1_replay_acceptance import git_blob_sha
from feynmap.p2_3b_fidelity import (
    EXPORT_SCHEMA, FROZEN_MANIFEST_GIT_BLOB, export_contexts,
    load_manifest, score_answers, verify_source,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments/p2_3b_answer_manifest.json"
SOURCE = ROOT / "experiments/fixtures/p2_3b_fulfillment"


def _manifest():
    return load_manifest(MANIFEST)


def _scoring_manifest():
    """Use the real sealed contract but only the two tasks in the mini index."""
    value = copy.deepcopy(_manifest())
    keep = {"reserve-order-implementation", "missing-refund-identifier"}
    value["tasks"] = [row for row in value["tasks"] if row["id"] in keep]
    return value


def test_p23b_manifest_and_fresh_source_are_sealed_before_answers():
    assert git_blob_sha(MANIFEST.read_bytes()) == FROZEN_MANIFEST_GIT_BLOB
    manifest = _manifest()
    assert manifest["status"] == "preauthored_before_context_export_or_model_answers"
    assert len(manifest["tasks"]) == 6
    assert len(manifest["source"]["blobs"]) == 12
    assert [row["id"] for row in manifest["arms"]] == [
        "legacy", "symbol_evidence",
    ]
    declarations = verify_source(manifest, SOURCE)
    assert len(declarations) == 12
    assert ("reserve_order",) in declarations["fulfillment/service.py"]
    assert ("apply_priority_default",) in declarations[
        "fulfillment/migrations/0001_priority.py"
    ]
    assert ("formatShipmentStatus",) in declarations["client/format.js"]
    assert ("normalizeStatus",) in declarations["client/status.js"]


def test_manifest_tamper_is_rejected_before_context_generation(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_bytes(MANIFEST.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="oracle changed after pre-registration"):
        load_manifest(target)


def test_source_tamper_is_rejected_before_graph_analysis(tmp_path):
    replica = tmp_path / "fixture"
    copytree(SOURCE, replica)
    file = replica / "fulfillment/service.py"
    file.write_text(file.read_text(encoding="utf-8") + "\n# after freeze\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="frozen source blob mismatch"):
        verify_source(_manifest(), replica)


def test_context_export_uses_same_activation_and_model_packets_have_no_gold(tmp_path):
    manifest = _manifest()
    report = export_contexts(manifest, SOURCE, tmp_path / "export")
    assert report["schema"] == EXPORT_SCHEMA
    assert report["task_count"] == 6
    assert report["source_files_verified"] == 12
    assert report["default_policy_changed"] is False
    assert len(report["records"]) == 6 * 2 * 2
    model_records = [row for row in report["records"] if row["model_visible"]]
    assert len(model_records) == 12
    by_task_budget = {}
    for record in report["records"]:
        by_task_budget.setdefault((record["task_id"], record["budget"]), []).append(record)
        assert set(record["selected_node_ids"])
        assert record["delivered_tokens_estimate"] <= next(
            row["max_tokens"] for row in manifest["budgets"]
            if row["id"] == record["budget"]
        )
    assert all(len(rows) == 2 for rows in by_task_budget.values())

    files = sorted((tmp_path / "export/model_inputs").glob("*.json"))
    assert len(files) == 12
    for file in files:
        payload = json.loads(file.read_text(encoding="utf-8"))
        encoded = json.dumps(payload, sort_keys=True)
        assert "required_claims" not in encoded
        assert "unsupported_traps" not in encoded
        assert "expected_status" not in encoded
        assert "support_symbols" not in encoded
        assert "symbol_evidence" not in encoded
        assert "legacy" not in encoded
        assert payload["packet_id"] == file.stem
        assert payload["answer_instruction"] == manifest["answer_protocol"]["instruction"]


def _mini_index():
    common_support = {
        "validate-before-mutation": {
            "lexical_groups": [["reserve_order"], ["ensure_stock"], ["before"], ["quantity"]],
            "support": [], "support_node_ids": ["n-reserve", "n-ensure"],
        },
        "decrement-on-success": {
            "lexical_groups": [["quantity"], ["decrement"], ["requested"]],
            "support": [], "support_node_ids": ["n-reserve"],
        },
        "returns-audit-message": {
            "lexical_groups": [["reservation_message"], ["returns"], ["remaining"]],
            "support": [], "support_node_ids": ["n-reserve"],
        },
    }
    def answer_record(packet_id, arm, tokens):
        return {
            "packet_id": packet_id,
            "task_id": "reserve-order-implementation",
            "arm": arm, "budget": "standard", "model_visible": True,
            "expected_status": "answer", "expected_missing_identifiers": [],
            "selected_node_ids": ["n-reserve", "n-ensure"],
            "selected_edge_ids": ["e-call"],
            "delivered_tokens_estimate": tokens,
            "delivery_sufficient": True,
            "unresolved_query_identifiers": [],
            "support_index": copy.deepcopy(common_support),
            "unsupported_traps": [{"id": "db", "any_phrases": ["database transaction"]}],
        }
    def missing_record(packet_id, arm, tokens, sufficient, unresolved):
        return {
            "packet_id": packet_id,
            "task_id": "missing-refund-identifier",
            "arm": arm, "budget": "standard", "model_visible": True,
            "expected_status": "need_more_context",
            "expected_missing_identifiers": ["issue_refund"],
            "selected_node_ids": ["n-cancel"], "selected_edge_ids": [],
            "delivered_tokens_estimate": tokens,
            "delivery_sufficient": sufficient,
            "unresolved_query_identifiers": unresolved,
            "support_index": {},
            "unsupported_traps": [{"id": "invent", "any_phrases": ["payment provider"]}],
        }
    return {
        "schema": EXPORT_SCHEMA,
        "manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
        "records": [
            answer_record("answerpacket", "legacy", 1000),
            answer_record("symbolpacket", "symbol_evidence", 700),
            missing_record("legacyunknown", "legacy", 500, True, []),
            missing_record("symbolunknown", "symbol_evidence", 350, False, ["issue_refund"]),
        ],
    }


def _answer(claim_nodes):
    return {
        "status": "answer",
        "claims": [
            {"text": "reserve_order calls ensure_stock before changing quantity", "evidence_nodes": claim_nodes, "evidence_edges": ["e-call"]},
            {"text": "quantity is decremented by the requested quantity", "evidence_nodes": ["n-reserve"], "evidence_edges": []},
            {"text": "reserve_order returns reservation_message with remaining quantity", "evidence_nodes": ["n-reserve"], "evidence_edges": []},
        ],
        "missing_identifiers": [],
    }


def _write_run(tmp_path, *, eligible=False, corrupt_symbol=False, trap=False):
    answers = tmp_path / "answers"
    answers.mkdir()
    run = {
        "schema": "feynmap.p2_3b_model_run.v1",
        "provider": "test", "model": "fixture",
        "eligible_for_shipping_decision": eligible,
        "usage_by_packet": {},
    }
    (answers / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (answers / "answerpacket.json").write_text(
        json.dumps(_answer(["n-reserve", "n-ensure"])), encoding="utf-8"
    )
    symbol = _answer(["invented"] if corrupt_symbol else ["n-reserve", "n-ensure"])
    if trap:
        symbol["claims"].append({
            "text": "It commits to a database transaction",
            "evidence_nodes": ["n-reserve"], "evidence_edges": [],
        })
    (answers / "symbolpacket.json").write_text(json.dumps(symbol), encoding="utf-8")
    abstain = {
        "status": "need_more_context", "claims": [],
        "missing_identifiers": ["issue_refund"],
    }
    (answers / "legacyunknown.json").write_text(json.dumps(abstain), encoding="utf-8")
    (answers / "symbolunknown.json").write_text(json.dumps(abstain), encoding="utf-8")
    return answers


def test_answer_scorer_rewards_grounded_fidelity_but_interactive_run_cannot_promote(tmp_path):
    answers = _write_run(tmp_path, eligible=False)
    result = score_answers(_scoring_manifest(), _mini_index(), answers)
    assert result["metric_gate_passed"] is True
    assert result["shipping_decision"] == "keep_opt_in_model_run_not_eligible_for_shipping_decision"
    by_arm = {row["arm"]: row for row in result["summaries"]}
    assert by_arm["legacy"]["required_claim_recall"] == 1.0
    assert by_arm["symbol_evidence"]["required_claim_recall"] == 1.0
    assert by_arm["symbol_evidence"]["correct_request_more_context_tasks"] == 1
    assert by_arm["symbol_evidence"]["context_estimated_tokens_sum"] < by_arm["legacy"]["context_estimated_tokens_sum"]


def test_answer_scorer_rejects_invalid_citation_and_preregistered_unsupported_trap(tmp_path):
    answers = _write_run(tmp_path, eligible=True, corrupt_symbol=True, trap=True)
    result = score_answers(_scoring_manifest(), _mini_index(), answers)
    symbol = next(row for row in result["details"] if row["packet_id"] == "symbolpacket")
    assert symbol["citations_valid"] is False
    assert "db" in symbol["unsupported_trap_hits"]
    assert result["metric_gate_passed"] is False
    assert result["shipping_decision"] == "keep_opt_in_downstream_fidelity_gate_not_met"


def test_unresolved_question_answering_facts_is_failure(tmp_path):
    answers = _write_run(tmp_path)
    invented = {
        "status": "answer",
        "claims": [{
            "text": "issue_refund calls a payment provider",
            "evidence_nodes": ["n-cancel"], "evidence_edges": [],
        }],
        "missing_identifiers": [],
    }
    (answers / "symbolunknown.json").write_text(json.dumps(invented), encoding="utf-8")
    result = score_answers(_scoring_manifest(), _mini_index(), answers)
    row = next(item for item in result["details"] if item["packet_id"] == "symbolunknown")
    assert row["status_ok"] is False
    assert row["no_factual_answer_when_unresolved"] is False
    assert "invent" in row["unsupported_trap_hits"]
    assert row["task_passed"] is False
