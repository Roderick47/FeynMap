"""P2.3b final shipping guard cannot promote a 0%-vs-0% tie."""
from feynmap.p2_3b_shipping import apply_shipping_guard


def _score(*, legacy_recall=0.0, symbol_recall=0.0,
           legacy_passes=0, symbol_passes=0,
           comparative=True, eligible=True):
    def summary(arm, recall, passes):
        return {
            "arm": arm,
            "answerable_tasks": 5,
            "answerable_task_passes": passes,
            "required_claim_recall": recall,
            "unsupported_trap_hits": 0,
            "invalid_or_uncited_claims": 0,
            "correct_request_more_context_tasks": 1,
            "request_more_context_tasks": 1,
            "context_estimated_tokens_sum": 1000 if arm == "legacy" else 700,
        }
    return {
        "metric_gate_passed": comparative,
        "shipping_decision": "raw-comparative-decision",
        "model_run": {"eligible_for_shipping_decision": eligible},
        "summaries": [
            summary("legacy", legacy_recall, legacy_passes),
            summary("symbol_evidence", symbol_recall, symbol_passes),
        ],
    }


def test_zero_recall_tie_cannot_promote_even_if_relative_gate_passes():
    result = apply_shipping_guard(_score())
    assert result["comparative_metric_gate_passed"] is True
    assert result["absolute_fidelity_gate_passed"] is False
    assert result["final_shipping_decision"] == (
        "keep_opt_in_absolute_downstream_fidelity_not_met"
    )


def test_full_fidelity_nonblind_run_still_cannot_promote():
    result = apply_shipping_guard(_score(
        legacy_recall=1.0, symbol_recall=1.0,
        legacy_passes=5, symbol_passes=5,
        eligible=False,
    ))
    assert result["absolute_fidelity_gate_passed"] is True
    assert result["final_shipping_decision"] == (
        "keep_opt_in_model_run_not_eligible_for_shipping_decision"
    )


def test_full_fidelity_blind_run_requires_comparative_gate_too():
    failed = apply_shipping_guard(_score(
        legacy_recall=1.0, symbol_recall=1.0,
        legacy_passes=5, symbol_passes=5,
        comparative=False, eligible=True,
    ))
    assert failed["final_shipping_decision"] == (
        "keep_opt_in_comparative_fidelity_gate_not_met"
    )

    passed = apply_shipping_guard(_score(
        legacy_recall=1.0, symbol_recall=1.0,
        legacy_passes=5, symbol_passes=5,
        comparative=True, eligible=True,
    ))
    assert passed["final_shipping_decision"].startswith("eligible_to_promote")
