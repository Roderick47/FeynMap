import json
from pathlib import Path

from feynmap.p2_4d_evaluate import FROZEN_MANIFEST_GIT_BLOB, load_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "experiments" / "p2_4d_downstream_manifest.json"
CHECKPOINT = REPO_ROOT / "experiments" / "results" / "p2_4d_20261001_fresh_downstream.json"
RUN = REPO_ROOT / "experiments" / "p2_4d_answers" / "run.json"


def test_p2_4d_manifest_freeze_identity_and_source_order():
    manifest = load_manifest(MANIFEST)
    assert FROZEN_MANIFEST_GIT_BLOB == "153bd1d1e0912c6b008ac8b0ba00c76c3529662e"
    assert manifest["source"]["source_commit_before_oracle"] == (
        "3d34727a39275576cfbff3f630bf8b1998e70a0b"
    )
    assert len(manifest["tasks"]) == 8
    assert sum(task["expected_status"] == "answer" for task in manifest["tasks"]) == 7
    assert sum(
        len(task.get("required_behavior_patterns", ())) for task in manifest["tasks"]
    ) == 17
    assert sum(len(task.get("required_claims", ())) for task in manifest["tasks"]) == 20


def test_p2_4d_checkpoint_preserves_fresh_and_nonblind_boundaries():
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    assert checkpoint["status"] == (
        "fresh_representation_complete_oracle_blind_downstream_pending"
    )
    fresh = checkpoint["fresh_representation"]
    assert fresh["required_behavior_patterns"] == 17
    assert fresh["symbol_evidence"]["matched_patterns"] == 0
    assert fresh["behavior_repaired"]["matched_patterns"] == 16
    assert fresh["gate_passed"] is True

    downstream = checkpoint["nonblind_downstream_diagnostic"]
    assert downstream["required_answer_claims"] == 20
    assert downstream["behavior_repaired"]["matched_claims"] == 19
    assert downstream["behavior_repaired"]["grounded_claims"] == 19
    assert downstream["behavior_repaired"]["answerable_task_passes"] == 6
    assert downstream["eligible_for_shipping_decision"] is False
    assert downstream["absolute_fidelity_guard_passed"] is False
    assert checkpoint["decision"]["legacy_default_changed"] is False


def test_p2_4d_interactive_run_cannot_be_shipping_eligible():
    run = json.loads(RUN.read_text(encoding="utf-8"))
    assert run["oracle_exposure"] is True
    assert run["eligible_for_shipping_decision"] is False
