"""P2.2: no gold leakage, exact source/oracle seals, token attribution and honest misses."""
import copy
import json
from pathlib import Path

import pytest

from feynmap.context_pipeline import SparseContextPipeline
from feynmap.delivery_channels import DeliveryChannelPolicy
from feynmap.engine import FeynMapEngine
from feynmap.minimal_context import MinimalContextBudget
from feynmap.p1_replay_acceptance import git_blob_sha
from feynmap.p2_delivery_collect import collect
from feynmap.p2_delivery_experiment import (
    FROZEN_MANIFEST_GIT_BLOB, _graph_label, _measure_arm, _validate_labels,
    _validate_source_blobs, evaluate_fixture, load_frozen_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "experiments/p2_2_delivery_manifest.json"
STOCK_ROOT = ROOT / "experiments/fixtures/p2_channels"


def _manifest():
    return load_frozen_manifest(MANIFEST_PATH)


def test_p2_oracle_frozen_before_running_and_source_blobs_match():
    assert git_blob_sha(MANIFEST_PATH.read_bytes()) == FROZEN_MANIFEST_GIT_BLOB
    manifest = _manifest()
    assert len(manifest["tasks"]) == 8
    assert [item["id"] for item in manifest["budgets"]] == ["tight", "standard"]
    assert [item["id"] for item in manifest["arms"]] == [
        "legacy", "source_first_p21", "balanced_floor1",
    ]
    source = manifest["source_fixtures"]["stockroom-independent"]
    verified = _validate_source_blobs(source, STOCK_ROOT)
    assert verified["files_verified"] == len(source["blobs"]) == 10
    local_tasks = [
        task for task in manifest["tasks"]
        if task["cohort"] == "stockroom-independent"
    ]
    _validate_labels(local_tasks, source, verified["declarations"])
    assert len(local_tasks) == 5
    assert {task["intent"] for task in local_tasks} == {
        "implementation", "test", "migration",
    }


def test_manifest_tampering_cannot_silently_change_expectations(tmp_path):
    mutable = tmp_path / "oracle.json"
    mutable.write_bytes(MANIFEST_PATH.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="manifest changed after oracle freeze"):
        load_frozen_manifest(mutable)


def test_source_blob_tampering_cannot_turn_a_new_case_into_a_pass(tmp_path):
    from shutil import copytree
    replica = tmp_path / "stockroom"
    copytree(STOCK_ROOT, replica)
    target = replica / "stockroom/rules.py"
    target.write_text(
        target.read_text() + "\n# Added after the source oracle froze.\n",
        encoding="utf-8",
    )
    source = _manifest()["source_fixtures"]["stockroom-independent"]
    with pytest.raises(ValueError, match="frozen source blob mismatch"):
        _validate_source_blobs(source, replica)


def test_independently_authored_missing_declaration_is_not_auto_created():
    manifest = _manifest()
    source = manifest["source_fixtures"]["stockroom-independent"]
    verified = _validate_source_blobs(source, STOCK_ROOT)
    tasks = [
        copy.deepcopy(task) for task in manifest["tasks"]
        if task["cohort"] == "stockroom-independent"
    ]
    tasks[0]["required_symbols"][0]["name"] = "not_in_the_checked_in_source"
    with pytest.raises(ValueError, match="absent in frozen source"):
        _validate_labels(tasks, source, verified["declarations"])


def test_live_independent_stockroom_measures_every_policy_budget_honestly():
    report = evaluate_fixture(
        _manifest(), "stockroom-independent", STOCK_ROOT,
    )
    assert report["status"] == "measured_with_source_gaps"
    assert report["task_count"] == 5
    assert len(report["source_graph_identity_sha256"]) == 64
    assert report["source_files_blobs_verified"] == 10
    for task in report["tasks"]:
        assert task["shared_activation"]["activated_nodes"] >= 1
        assert len(task["budget_comparisons"]) == 2
        assert task["intent_authored"] in {"implementation", "test", "migration"}
        for budget in task["budget_comparisons"]:
            assert len(budget["arms"]) == 3
            expected = budget["limits"]
            selected = [arm["selected_node_ids"] for arm in budget["arms"]]
            activated = set(task["shared_activation"]["source_node_ids"])
            for arm in budget["arms"]:
                assert arm["all_selected_from_shared_activation_with_endpoints"]
                assert set(arm["selected_node_ids"]).issubset(activated)
                assert arm["estimated_context_tokens"] <= expected["max_tokens"]
                assert arm["nodes"] <= expected["max_nodes"]
                assert arm["edges"] <= expected["max_edges"]
                chars = arm["token_characters_by_source_role"]
                assert chars["exact_char_accounting_reconciles"]
                assert chars["estimated_full_tokens"] == arm["estimated_context_tokens"]
                assert (
                    sum(chars["source_role_node_chars"].values())
                    + chars["common_edges_anchors_metadata_separator_chars"]
                ) == chars["deterministic_full_json_characters"]
                assert sum(arm["node_counts_by_channel"].values()) == arm["nodes"]
                assert len(arm["required_symbols"]) >= 2
                assert set(row["outcome"] for row in arm["required_symbols"]) <= {
                    "not_indexed", "ambiguous", "not_activated",
                    "activated_but_not_delivered", "delivered",
                }
            # Identical activation is reused for the legacy, P2.1 and
            # balanced-floor arms. Their selected node lists may differ.
            assert len(selected) == 3
    assert {item["id"] for item in report["tasks"]} == {
        task["id"] for task in _manifest()["tasks"]
        if task["cohort"] == "stockroom-independent"
    }


def test_selection_never_reads_gold_labels_before_packing():
    manifest = _manifest()
    task = next(row for row in manifest["tasks"]
                if row["id"] == "stock-negative-implementation")
    budget = next(row for row in manifest["budgets"]
                  if row["id"] == "standard")
    arm = next(row for row in manifest["arms"]
               if row["id"] == "source_first_p21")
    graph = FeynMapEngine().analyze(
        str(STOCK_ROOT), language="python", framework="none",
    )
    pipeline = SparseContextPipeline(graph)
    conf = manifest["activation"]
    activation = pipeline.search.concept(
        task["query"], seed_limit=conf["seed_limit"],
        candidate_limit=conf["candidate_limit"],
        max_depth=conf["max_depth"], beam_width=conf["beam_width"],
        max_nodes=conf["max_nodes"], direction=conf["direction"],
    ).search
    original = _measure_arm(
        graph, activation, task, budget, arm, pipeline.packer,
    )
    manipulated = copy.deepcopy(task)
    manipulated["required_symbols"] = [{
        "file": "stockroom/missing.py", "name": "not_a_source_symbol",
    }]
    manipulated["required_files"] = ["stockroom/missing.py"]
    manipulated["useful_support_symbols"] = []
    manipulated["distractor_symbols"] = []
    # The experimental evaluator sees the label change, but the actual
    # Packer never receives the label list. Gold cannot steer selection.
    observed = _measure_arm(
        graph, activation, manipulated, budget, arm, pipeline.packer,
    )
    assert original["selected_node_ids"] == observed["selected_node_ids"]
    assert original["selected_edge_ids"] == observed["selected_edge_ids"]
    assert original["estimated_context_tokens"] == observed["estimated_context_tokens"]
    assert original["required_symbol_recall"] != observed["required_symbol_recall"] or (
        original["required_files"] != observed["required_files"]
    )


def test_collection_exposes_incomplete_external_fixture_and_role_accounting():
    manifest = _manifest()
    report = evaluate_fixture(
        manifest, "stockroom-independent", STOCK_ROOT,
    )
    result = collect(manifest, {"stockroom-independent": report})
    assert result["status"] == "integrity_failure"
    assert any("fixture report identities" in issue
               for issue in result["integrity_errors"])
    assert result["tasks"] == 5
    assert len(result["summaries"]) == 6
    assert all(entry["file_recall"] is not None for entry in result["summaries"])

    altered = copy.deepcopy(report)
    first = altered["tasks"][0]["budget_comparisons"][0]["arms"][0]
    first["token_characters_by_source_role"]["node_chars"] += 23
    corrupted = collect(manifest, {"stockroom-independent": altered})
    assert any("character budget" in issue
               for issue in corrupted["integrity_errors"])


def test_symbol_oracle_requires_matching_source_not_name_only():
    graph = FeynMapEngine().analyze(
        str(STOCK_ROOT), language="python", framework="none",
    )
    exact = _graph_label(
        graph, {"file": "stockroom/inventory.py", "name": "apply_stock_movement"},
    )
    other = _graph_label(
        graph, {"file": "stockroom/migrations/0002_legacy_pricing.py",
                "name": "apply_stock_movement"},
    )
    assert exact["graph_index_status"] == "unique"
    assert other["graph_index_status"] == "not_indexed"
    assert exact["node_ids"] != other["node_ids"]
