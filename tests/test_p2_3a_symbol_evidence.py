"""P2.3a: preregistered mixed-language evidence and isolated opt-in policy."""
import copy
from pathlib import Path

import pytest

from feynmap.context import estimate_tokens
from feynmap.core import (
    EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph,
    SemanticNode, SourceLocation,
)
from feynmap.delivery_channels import DeliveryChannelPolicy, TEST, MIGRATION, file_channel
from feynmap.engine import FeynMapEngine
from feynmap.judgment.search import GuidedSearchResult, SearchHit
from feynmap.minimal_context import MinimalContextBudget, MinimalContextPacker
from feynmap.context_pipeline import SparseContextPipeline
from feynmap.p1_replay_acceptance import git_blob_sha
from feynmap.p2_3a_replay import (
    NEW_SOURCE_MANIFEST_BLOB, _javascript_definitions, compare,
    load_fresh_manifest, verify_fresh_source,
)
from feynmap.p2_delivery_experiment import _measure_arm

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments/fixtures/p2_3a_dispatch"
MANIFEST = ROOT / "experiments/p2_3a_source_manifest.json"


def _manifest():
    return load_fresh_manifest(MANIFEST)


def test_fresh_symbol_oracle_was_sealed_and_declarations_exist_independently():
    assert git_blob_sha(MANIFEST.read_bytes()) == NEW_SOURCE_MANIFEST_BLOB
    manifest = _manifest()
    assert len(manifest["tasks"]) == 8
    assert len(manifest["source"]["blobs"]) == 12
    result = verify_fresh_source(manifest, SOURCE)
    assert result["files_verified"] == 12
    assert ("normalizeSeverity",) in result["declarations"]["client/severity.js"]
    assert ("testUrgentTicketAlert",) in result["declarations"]["client/presenter.test.js"]
    assert ("backfill_missing_priority",) in result["declarations"][
        "dispatch/migrations/0004_backfill_priority.py"
    ]
    assert {"implementation", "test", "migration"} == {
        task["intent"] for task in manifest["tasks"]
    }


def test_fresh_oracle_tampering_is_rejected_before_analysis(tmp_path):
    edited = tmp_path / "manifest.json"
    edited.write_bytes(MANIFEST.read_bytes() + b" ")
    with pytest.raises(ValueError, match="tampered after pre-registration"):
        load_fresh_manifest(edited)


def test_source_blob_mutation_is_rejected_not_relabelled(tmp_path):
    from shutil import copytree
    path = tmp_path / "source"
    copytree(SOURCE, path)
    target = path / "dispatch/service.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# change after freeze\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source file blob mismatch"):
        verify_fresh_source(_manifest(), path)


def test_javascript_source_independent_declarations_not_graph_as_oracle():
    defs = _javascript_definitions(SOURCE / "client/presenter.js")
    assert defs == {("formatTicketAlert",), ("formatUnrelatedInvoice",)}
    assert file_channel("client/presenter.test.js") == TEST
    assert file_channel("dispatch/migrations/0004_backfill_priority.py") == MIGRATION


def _source_node(identifier, name, path):
    location = SourceLocation(path, line=2)
    return SemanticNode(
        id=identifier, name=name, qualified_name=name,
        kind=NodeKind.FUNCTION, language="python", location=location,
        evidence=[
            Evidence(EvidenceKind.STATIC, "fixture.explicit_source_definition",
                     "Independent declaration", location, 0.97),
        ],
    )


def test_symbol_evidence_requires_existing_direct_behavioral_edge_when_activated():
    source = _source_node("service", "processAssignment", "service.py")
    target = _source_node("rule", "checkCapacity", "rules.py")
    irrelevant = _source_node("noise", "unrelatedBilling", "billing.py")
    edge = SemanticEdge(
        id="actual-call", source=source.id, target=target.id,
        kind=EdgeKind.CALLS, confidence=0.97,
        evidence=[Evidence(
            EvidenceKind.STATIC, "fixture.explicit_call",
            "processAssignment invokes checkCapacity",
            SourceLocation("service.py", line=5), 0.97,
        )],
    )
    graph = SemanticGraph(nodes=[source, target, irrelevant], edges=[edge])
    search = GuidedSearchResult(
        mode="concept",
        query="How does processAssignment call checkCapacity?",
        roots=[source],
        hits=[
            SearchHit(source, depth=0),
            SearchHit(target, depth=1, parent_id=source.id,
                      via_edge_id=edge.id),
            SearchHit(irrelevant, depth=1),
        ],
        edges=[edge], trace=[], provider=None, model=None,
        exhausted=True, truncated=False,
    )
    packer = MinimalContextPacker(graph)
    budget = MinimalContextBudget(
        max_tokens=1600, max_nodes=12, max_edges=12,
    )
    packed = packer.pack(
        search, budget=budget,
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
    )
    assert packed.sufficient
    assert {"service", "rule"} <= set(packed.selected_node_ids)
    assert "actual-call" in packed.selected_edge_ids
    assert packed.delivered_tokens <= budget.max_tokens
    assert packed.delivered_tokens == estimate_tokens(packed.payload)
    assert packed.selected_node_ids and packed.activated_nodes == 3
    assert packed.payload["relationships"][0]["relationship"] == EdgeKind.CALLS.value


def test_new_mode_never_invents_relationship_if_only_nodes_activated():
    source = _source_node("service", "processAssignment", "service.py")
    target = _source_node("rule", "checkCapacity", "rules.py")
    graph = SemanticGraph(nodes=[source, target])
    search = GuidedSearchResult(
        mode="concept",
        query="How does processAssignment call checkCapacity?",
        roots=[source],
        hits=[SearchHit(source, depth=0), SearchHit(target, depth=1)],
        edges=[], trace=[], provider=None, model=None,
        exhausted=True, truncated=False,
    )
    packed = MinimalContextPacker(graph).pack(
        search,
        budget=MinimalContextBudget(max_tokens=1600, max_nodes=12, max_edges=12),
        delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
    )
    assert {"service", "rule"} <= set(packed.selected_node_ids)
    assert not packed.selected_edge_ids
    assert not packed.payload["relationships"]


def test_fresh_eight_task_comparison_uses_single_shared_activation_per_task():
    report = compare(_manifest(), SOURCE)
    assert report["schema"] == "feynmap.p2_3a_symbol_evidence_comparison.v1"
    assert report["fresh_source"] is True
    assert report["source_files_verified"] == 12
    assert report["task_count"] == 8
    assert len(report["summaries"]) == 6
    for task in report["tasks"]:
        assert task["shared_activation"]["nodes"] > 0
        for budget in task["budgets"]:
            assert [arm["arm"] for arm in budget["arms"]] == [
                "legacy", "p2_1_source_first", "p2_3a_symbol_evidence"
            ]
            ids = set(task["shared_activation"]["node_ids"])
            for arm in budget["arms"]:
                assert set(arm["selected_node_ids"]) <= ids
                assert arm["all_selected_from_shared_activation_with_endpoints"]
                assert arm["estimated_context_tokens"] <= budget["limits"]["max_tokens"]
                assert arm["nodes"] <= budget["limits"]["max_nodes"]
                assert arm["edges"] <= budget["limits"]["max_edges"]
                assert arm["token_characters_by_source_role"][
                    "exact_char_accounting_reconciles"
                ]
    for budget in ("standard", "tight"):
        summary = next(row for row in report["summaries"]
                       if row["budget"] == budget
                       and row["arm"] == "p2_3a_symbol_evidence")
        assert 0 <= summary["delivered_required_symbols"] <= summary[
            "activated_required_symbols"
        ]


def test_frozen_labels_change_scoring_not_new_policy_selection():
    manifest = _manifest()
    original = manifest["tasks"][0]
    graph = FeynMapEngine().analyze(
        str(SOURCE), language="auto", framework="none",
    )
    pipeline = SparseContextPipeline(graph)
    conf = manifest["activation"]
    search = pipeline.search.concept(
        original["query"], seed_limit=conf["seed_limit"],
        candidate_limit=conf["candidate_limit"],
        max_depth=conf["max_depth"], beam_width=conf["beam_width"],
        max_nodes=conf["max_nodes"], direction=conf["direction"],
    ).search
    budget = manifest["budgets"][1]
    arm = manifest["arms"][2]
    first = _measure_arm(
        graph, search, original, budget, arm, pipeline.packer,
    )
    altered = copy.deepcopy(original)
    altered["required_files"] = ["not/a/real/file.py"]
    altered["required_symbols"] = [{
        "file": "not/a/real/file.py", "name": "fabricated_result",
    }]
    altered["useful_support_symbols"] = []
    altered["distractor_symbols"] = []
    second = _measure_arm(
        graph, search, altered, budget, arm, pipeline.packer,
    )
    assert first["selected_node_ids"] == second["selected_node_ids"]
    assert first["selected_edge_ids"] == second["selected_edge_ids"]
    assert first["estimated_context_tokens"] == second["estimated_context_tokens"]
    assert second["required_symbol_recall"] == 0.0
    assert first["required_symbols"] != second["required_symbols"]


def test_normal_p2_1_policy_is_still_accepted_and_legacy_default_unchanged():
    assert DeliveryChannelPolicy(mode="implementation_first").normalized()
    assert DeliveryChannelPolicy(mode="symbol_evidence").normalized()
    with pytest.raises(ValueError, match="unsupported"):
        DeliveryChannelPolicy(mode="gold_label_lookup").normalized()
    graph = FeynMapEngine().analyze(
        str(SOURCE), language="auto", framework="none",
    )
    query = _manifest()["tasks"][0]["query"]
    search = SparseContextPipeline(graph).search.concept(query).search
    packer = MinimalContextPacker(graph)
    budget = MinimalContextBudget(max_tokens=3200, max_nodes=24, max_edges=24)
    assert (
        packer.pack(search, budget=budget).to_dict()
        == packer.pack(search, budget=budget, delivery_policy=None).to_dict()
    )
