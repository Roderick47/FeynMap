"""Final P2.3b shipping guard layered over the frozen comparative scorer.

The pre-registered comparison says the candidate must not regress against
legacy. A tie between two unusable contexts technically satisfies that
relative test, so promotion also requires an absolute downstream-fidelity
floor. This guard was added after the first development score exposed the
0%-vs-0% degeneracy; it does not change source labels, model answers, or the
frozen comparative result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

FINAL_SCHEMA = "feynmap.p2_3b_shipping_decision.v1"


def apply_shipping_guard(score: Mapping[str, Any]) -> Dict[str, Any]:
    summaries = {row["arm"]: row for row in score.get("summaries", [])}
    if set(summaries) != {"legacy", "symbol_evidence"}:
        raise ValueError("P2.3b shipping guard requires legacy and symbol_evidence summaries")
    symbol = summaries["symbol_evidence"]
    absolute_fidelity = (
        symbol.get("required_claim_recall") == 1.0
        and symbol.get("answerable_task_passes") == symbol.get("answerable_tasks")
        and symbol.get("unsupported_trap_hits") == 0
        and symbol.get("invalid_or_uncited_claims") == 0
        and symbol.get("correct_request_more_context_tasks")
        == symbol.get("request_more_context_tasks")
    )
    comparative = bool(score.get("metric_gate_passed"))
    eligible = bool((score.get("model_run") or {}).get("eligible_for_shipping_decision"))

    if not absolute_fidelity:
        decision = "keep_opt_in_absolute_downstream_fidelity_not_met"
    elif not comparative:
        decision = "keep_opt_in_comparative_fidelity_gate_not_met"
    elif not eligible:
        decision = "keep_opt_in_model_run_not_eligible_for_shipping_decision"
    else:
        decision = "eligible_to_promote_symbol_evidence_default_subject_to_full_regression_ci"

    return {
        "schema": FINAL_SCHEMA,
        "comparative_metric_gate_passed": comparative,
        "absolute_fidelity_gate_passed": absolute_fidelity,
        "model_run_eligible_for_shipping_decision": eligible,
        "final_shipping_decision": decision,
        "candidate_summary": symbol,
        "legacy_summary": summaries["legacy"],
        "comparative_scorer_decision": score.get("shipping_decision"),
        "default_policy_changed": False,
        "post_registration_guard_note": (
            "Added after the first nonblind development score showed that the "
            "frozen relative no-regression criterion can be true when both arms "
            "have zero required-claim recall. This guard is strictly more "
            "conservative: it does not alter the oracle, answers, or relative "
            "score and cannot turn a failed comparison into a pass."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    score = json.loads(Path(args.score).read_text(encoding="utf-8"))
    result = apply_shipping_guard(score)
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "comparative_metric_gate_passed": result["comparative_metric_gate_passed"],
        "absolute_fidelity_gate_passed": result["absolute_fidelity_gate_passed"],
        "final_shipping_decision": result["final_shipping_decision"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
