"""P1.7: frozen before/after replay of the source-authored P1.1 development set.

This is an acceptance REPORT, not a framework adapter or a new search policy.
Neither the frozen manifest nor the baseline is generated from current output.
The corpus contains positive labels only: it cannot establish precision or an
independent false-positive rate. Keep unmeasured claims explicitly unknown.
Compatible with Python 3.8; stdlib-only so the collector need not install
dependencies of any external source repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


SCHEMA = "feynmap.p1_7_replay_acceptance.v1"
MANIFEST_SCHEMA = "feynmap.external_framework_baseline.v1"
BASELINE_SCHEMA = "feynmap.p1_external_baseline_summary.v1"
REPORT_SCHEMA = "feynmap.p1_external_baseline.v1"

# Git blob identities were frozen before P1.7, not derived from the updated
# source graph. Changing either oracle requires an explicit new experiment.
FROZEN_MANIFEST_GIT_BLOB = "721221722b2667ed107ec7f99a956677ad5531a6"
FROZEN_BASELINE_GIT_BLOB = "d6ab3b4f8aaaa540b7b57aff78594d1ecfdaf545"

_PASSED_BASELINE_STATUSES = {
    "matched_relationship", "matched_route", "matched_named_route",
    "all_essential_delivered", "minified_assets_skipped_without_crash",
}
_P12_TIERS = {
    "cbv-book-list-model": "supported",
    "cbv-book-detail-model": "supported",
    "cbv-book-list-default-template": "inferred",
    "cbv-book-detail-default-template": "inferred",
    "cbv-explicit-template": "supported",
}
_REQUIRED_PROBES = {
    "mdn-django-local-library": set(_P12_TIERS) | {"named-url-books"},
    "grinberg-microblog": {"api-token-post", "api-token-delete"},
    "django-rest-framework": {"throttling-implementation-recall", "vendored-js-no-crash"},
}
_DRf_REQUIRED = {"rest_framework/serializers.py", "rest_framework/fields.py"}
_LOCKED_APP_MEMBERSHIP = {
    "mdn-django-local-library": 29,
    "grinberg-microblog": 0,
    "django-rest-framework": 20,
}


def git_blob_sha(data: bytes) -> str:
    """Return Git's canonical blob digest, independent of a local .git folder."""
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _initial_pass(row: Mapping[str, Any]) -> bool:
    return row.get("status") in _PASSED_BASELINE_STATUSES


def _path(item: Mapping[str, Any]) -> str:
    return str(item.get("source_file") or "").replace("\\", "/")


def _source_evidence(probe: Mapping[str, Any],
                     observed: Mapping[str, Any]) -> Dict[str, Any]:
    category = probe["category"]
    if category in {"framework_relationship", "framework_inference"}:
        matches = observed.get("matching_edges") or []
        tiers = [row.get("confidence_tier") for row in matches]
        return {
            "kind": "semantic_edge",
            "expected_relationship": probe.get("relationship"),
            "target_file": probe.get("target_file"),
            "matching_edge_count": len(matches),
            "edge_kinds": [row.get("kind") for row in matches],
            "confidence_tiers": tiers,
            "detectors": [row.get("detectors") or [] for row in matches],
        }
    if category == "http_route":
        if probe.get("expected_target"):
            rows = observed.get("matching_named_contracts") or []
        else:
            rows = [
                row for row in (observed.get("observed_contracts") or [])
                if row.get("target") == probe.get("expected_path")
            ]
        return {
            "kind": "source_registered_http_contract",
            "matching_contract_count": len(rows),
            "contracts": [{
                key: row.get(key)
                for key in (
                    "target", "methods", "name", "route_name", "framework",
                    "confidence", "source_file", "source_line", "evidence_kind",
                    "derivation", "blueprint_id", "registration_file",
                    "registration_line", "url_prefix",
                ) if key in row
            } for row in rows],
        }
    return {"kind": "runtime_pipeline_or_adapter_observation"}


def _retrieval_record(probe: Mapping[str, Any],
                      before: Mapping[str, Any],
                      after: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if probe["category"] != "retrieval":
        return None
    essential = set(probe["essential_files"])
    delivered_before = set(before.get("delivered_files") or [])
    activated_after = set(after.get("activated_files") or [])
    delivered_after = set(after.get("delivered_files") or [])
    return {
        "query": probe["query"],
        "essential_files": sorted(essential),
        "baseline_delivered_files": sorted(delivered_before),
        "current_activated_files": sorted(activated_after),
        "current_delivered_files": sorted(delivered_after),
        "baseline_delivery_essential_files": sorted(essential & delivered_before),
        "current_activation_essential_files": sorted(essential & activated_after),
        "current_delivery_essential_files": sorted(essential & delivered_after),
        "current_missing_delivered": sorted(essential - delivered_after),
        "baseline_delivered_essential_count": len(essential & delivered_before),
        "current_activated_essential_count": len(essential & activated_after),
        "current_delivered_essential_count": len(essential & delivered_after),
        "essential_denominator": len(essential),
        "current_activated_nodes": after.get("activated_node_count"),
        "current_delivered_nodes": after.get("delivered_node_count"),
        "current_delivered_tokens": after.get("delivered_context_tokens"),
        "baseline_delivered_node_channels": (
            before.get("delivered_channel_node_counts") or {}
        ),
        "current_delivered_node_channels": (
            after.get("delivered_channels_by_node_count") or {}
        ),
        "note": (
            "Activation and delivery are distinct. Baseline summary records "
            "delivered files, but not a complete baseline activated-file set. "
            "Channel shares are node counts, not token shares."
        ),
    }


def _metrics(old: Mapping[str, Any], new: Mapping[str, Any]) -> Dict[str, Any]:
    g = new.get("graph") or {}
    return {
        "baseline": {
            "nodes": old.get("graph_nodes"),
            "edges": old.get("graph_edges"),
            "analysis_elapsed_ms": old.get("analysis_elapsed_ms"),
            "process_peak_rss_kb": old.get("process_peak_rss_kb"),
            "raw_unmatched_contracts": old.get("raw_unresolved_contracts"),
            "synthetic_appconfig_edges": old.get("app_config_membership_edges"),
        },
        "current": {
            "nodes": g.get("nodes"),
            "edges": g.get("edges"),
            "analysis_elapsed_ms": new.get("analysis_elapsed_ms"),
            "process_peak_rss_kb": new.get("process_peak_rss_kb"),
            "raw_unmatched_contracts": g.get("unresolved_contract_count"),
            "synthetic_appconfig_edges": g.get("app_config_membership_edges"),
            "source_app_membership_observations": (
                g.get("app_config_source_membership_count")
            ),
            "integration_diagnostics_v2": {
                key: value for key, value in
                (g.get("integration_diagnostics_v2") or {}).items()
                if key in {
                    "raw_unmatched_contract_count", "actionable_review_candidate_count",
                    "non_actionable_or_unproven_count", "counts_by_category",
                    "python_intrinsic_unresolved_calls", "python_other_unresolved_calls",
                    "framework_unresolved_observations",
                }
            },
        },
        "interpretation": (
            "These are single-run counts and process-level measurements. "
            "More graph edges are not automatically more correct; one timing "
            "sample per fixture is not a comparative performance distribution."
        ),
    }


def compare_replay(manifest: Mapping[str, Any],
                   baseline: Mapping[str, Any],
                   reports: Mapping[str, Mapping[str, Any]],
                   *,
                   analyzer_revision: str = "unknown") -> Dict[str, Any]:
    """Build an auditable acceptance report; retain all failures and known gaps.

    Return status='failed' for integrity, regression or false-evidence errors.
    Do not convert an unsupported probe to a pass based on mere graph size.
    """
    errors: List[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("wrong frozen manifest schema")
    if baseline.get("schema") != BASELINE_SCHEMA:
        errors.append("wrong frozen initial baseline schema")
    fixture_specs = manifest.get("fixtures") or []
    old_specs = baseline.get("fixtures") or []
    if not isinstance(fixture_specs, list) or not isinstance(old_specs, list):
        errors.append("fixture lists must be JSON arrays")
        fixture_specs, old_specs = [], []
    keys = [entry.get("id") for entry in fixture_specs]
    if len(keys) != len(set(keys)):
        errors.append("duplicate manifest fixture id")
    old_keys = [entry.get("id") for entry in old_specs]
    if set(keys) != set(old_keys) or len(old_keys) != len(set(old_keys)):
        errors.append("original baseline fixture identities differ from manifest")
    if set(reports) != set(keys):
        errors.append("current report identities differ from frozen manifest: %s" %
                      sorted(set(keys) ^ set(reports)))

    old_by_id = {entry.get("id"): entry for entry in old_specs}
    replay_rows: List[Dict[str, Any]] = []
    before_total = 0
    after_total = 0
    total = 0
    recovered: List[str] = []
    regressed: List[str] = []
    still_unmet: List[str] = []
    positive_measured = 0

    for spec in fixture_specs:
        fixture_id = str(spec["id"])
        original = old_by_id.get(fixture_id) or {}
        current = reports.get(fixture_id) or {}
        expected_probes = spec.get("probes") or []
        old_probes = original.get("observed") or []
        new_probes = current.get("probes") or []
        target_ids = [row.get("id") for row in expected_probes]
        old_ids = [row.get("id") for row in old_probes]
        current_ids = [row.get("id") for row in new_probes]
        if (
            len(target_ids) != len(set(target_ids))
            or len(target_ids) != len(set(old_ids))
            or len(target_ids) != len(set(current_ids))
            or set(old_ids) != set(target_ids)
            or set(current_ids) != set(target_ids)
        ):
            errors.append(fixture_id + ": probe ids missing, duplicated or changed")
        if (original.get("repository"), original.get("commit")) != (
            spec.get("repository"), spec.get("commit")
        ):
            errors.append(fixture_id + ": original repository/revision mismatch")
        if current.get("schema") != REPORT_SCHEMA:
            errors.append(fixture_id + ": report schema mismatch")
        if (
            current.get("fixture_id") != fixture_id
            or current.get("repository") != spec.get("repository")
            or current.get("expected_commit") != spec.get("commit")
            or current.get("actual_commit") != spec.get("commit")
        ):
            errors.append(fixture_id + ": current pinned revision identity mismatch")
        if current.get("status") == "analysis_error":
            errors.append(fixture_id + ": analyzer failed")
        if current.get("probe_count") != len(expected_probes):
            errors.append(fixture_id + ": probe count mismatch")

        old_map = {row["id"]: row for row in old_probes}
        new_map = {row["id"]: row for row in new_probes}
        matched_before = 0
        matched_after = 0
        per_probe = []
        for probe in expected_probes:
            pid = probe["id"]
            historical = old_map.get(pid, {})
            latest = new_map.get(pid, {})
            observed = latest.get("observed") or {}
            before_met = _initial_pass(historical)
            after_met = latest.get("passed") is True
            if latest.get("expected_status") != probe.get("expected_status"):
                errors.append(pid + ": expected_status was altered")
            if not isinstance(latest.get("passed"), bool) or (
                latest.get("passed") is not observed.get("passed")
            ):
                errors.append(pid + ": observed/scored pass mismatch")
            matched_before += int(before_met)
            matched_after += int(after_met)
            before_total += int(before_met)
            after_total += int(after_met)
            total += 1
            positive_measured += 1
            label = fixture_id + "/" + pid
            transition = (
                "retained" if before_met and after_met
                else "recovered" if not before_met and after_met
                else "regressed" if before_met and not after_met
                else "still_unmet"
            )
            if transition == "recovered":
                recovered.append(label)
            elif transition == "regressed":
                regressed.append(label)
            elif transition == "still_unmet":
                still_unmet.append(label)
            evidence = _source_evidence(probe, observed)
            retrieval = _retrieval_record(probe, historical, observed)
            per_probe.append({
                "id": pid, "category": probe["category"],
                "expected_status": probe["expected_status"],
                "baseline_status": historical.get("status"),
                "current_status": observed.get("status"),
                "baseline_met": before_met,
                "current_met": after_met,
                "transition": transition,
                "source_evidence": evidence,
                "context": retrieval,
            })
            if pid in _P12_TIERS:
                edges = observed.get("matching_edges") or []
                if (
                    not after_met or len(edges) != 1
                    or edges[0].get("confidence_tier") != _P12_TIERS[pid]
                    or not edges[0].get("detectors")
                ):
                    errors.append(pid + ": required unique source edge/evidence tier regressed")
            if pid == "named-url-books":
                named = observed.get("matching_named_contracts") or []
                if (
                    not after_met or len(named) != 1
                    or named[0].get("target") != "/catalog/books/"
                    or named[0].get("name") != "books"
                    or named[0].get("framework") != "django"
                    or named[0].get("source_file") != "catalog/urls.py"
                    or named[0].get("source_line") != 8
                    or named[0].get("derivation") != "django.urls.static_registration"
                    or named[0].get("evidence_kind") != "static"
                ):
                    errors.append(pid + ": named static URL registration not proven")
            if pid in {"api-token-post", "api-token-delete"}:
                method = str(probe["expected_method"])
                candidates = observed.get("observed_contracts") or []
                grounded = [
                    row for row in candidates if
                    row.get("target") == "/api/tokens"
                    and row.get("methods") == [method]
                    and row.get("source_file") == "app/api/tokens.py"
                    and row.get("source_line") == probe["route_line"]
                    and row.get("registration_file") == "app/__init__.py"
                    and row.get("blueprint_declaration_file") == "app/api/__init__.py"
                    and row.get("blueprint_id") == "app.api.bp"
                    and row.get("derivation") == "flask.blueprint.registered_route"
                    and row.get("evidence_kind") == "static"
                ]
                if not after_met or len(grounded) != 1 or any(
                    row.get("target") == "/tokens" for row in candidates
                ):
                    errors.append(pid + ": registered Blueprint provenance/raw path regression")
            if pid == "serializer-implementation-recall":
                essential = set(probe["essential_files"])
                delivered = set(observed.get("delivered_files") or [])
                activated = set(observed.get("activated_files") or [])
                # The full P1.1 probe can pass only by delivery, never mere
                # activation or presence of an unrelated source graph edge.
                if after_met != essential.issubset(delivered):
                    errors.append(pid + ": delivery score contradicts selected context")
                if not essential.issubset(activated):
                    errors.append(pid + ": P1.6 implementation activation regressed")
            if pid in {"throttling-implementation-recall", "vendored-js-no-crash"} and not after_met:
                errors.append(pid + ": locked original passing evidence regressed")

        if matched_before != original.get("matched_probes"):
            errors.append(fixture_id + ": archived historical matched count inconsistent")
        if current.get("matched_probes") != matched_after:
            errors.append(fixture_id + ": new matched count contradicts per-probe results")
        if sorted(current.get("missing_probes") or []) != sorted(
            row["id"] for row in new_probes if row.get("passed") is False
        ):
            errors.append(fixture_id + ": new missing set inconsistent with per-probe results")

        graph = current.get("graph") or {}
        if not _integer(graph.get("nodes")) or not _integer(graph.get("edges")):
            errors.append(fixture_id + ": missing canonical graph totals")
        diagnostics = graph.get("diagnostics") or {}
        if diagnostics.get("error_count") != 0:
            errors.append(fixture_id + ": graph validation errors")
        if graph.get("app_config_membership_edges") != 0 or (
            graph.get("app_config_source_membership_count")
            != _LOCKED_APP_MEMBERSHIP.get(fixture_id)
        ):
            errors.append(fixture_id + ": P1.3 false dependency hub/membership regression")
        d = graph.get("integration_diagnostics_v2") or {}
        raw = graph.get("unresolved_contract_count")
        categories = d.get("counts_by_category") or {}
        if (
            not _integer(raw)
            or raw != d.get("raw_unmatched_contract_count")
            or raw != d.get("classified_unmatched_contract_count")
            or raw != sum(categories.values())
            or d.get("actionable_review_candidate_count", -1)
               + d.get("non_actionable_or_unproven_count", -1) != raw
        ):
            errors.append(fixture_id + ": unmatched integration diagnostics do not reconcile")
        if fixture_id == "mdn-django-local-library" and (
            (current.get("p1_3_django_impact") or {}).get("passed") is not True
        ):
            errors.append(fixture_id + ": P1.3 model impact/config locality regression")
        if fixture_id == "django-rest-framework":
            use = current.get("p1_6_drf_field_usage") or {}
            if (
                use.get("passed") is not True
                or use.get("metaclass_method_count") != 1
                or use.get("field_target_count") != 1
                or use.get("source_evidenced_edge_count") != 1
                or use.get("source_file") != "rest_framework/serializers.py"
                or use.get("target_file") != "rest_framework/fields.py"
            ):
                errors.append(fixture_id + ": unique static SerializerMetaclass Field use missing")

        replay_rows.append({
            "id": fixture_id, "repository": spec.get("repository"),
            "pinned_commit": spec.get("commit"),
            "baseline_probes_met": matched_before,
            "current_probes_met": matched_after,
            "probe_count": len(expected_probes),
            "metrics": _metrics(original, current),
            "probes": per_probe,
        })

    baseline_totals = baseline.get("totals") or {}
    if (
        baseline_totals.get("fixtures") != len(keys)
        or baseline_totals.get("probes") != total
        or baseline_totals.get("met") != before_total
        or baseline_totals.get("unmet") != total - before_total
        or baseline_totals.get("analysis_crashes") != 0
    ):
        errors.append("frozen baseline summary is internally inconsistent")
    for item in regressed:
        errors.append(item + ": previously matched positive probe regressed")
    for fixture_id, required in _REQUIRED_PROBES.items():
        current = next((row for row in replay_rows if row["id"] == fixture_id), {})
        observed = {row["id"]: row for row in current.get("probes", [])}
        for pid in sorted(required):
            if not (observed.get(pid) or {}).get("current_met"):
                errors.append(fixture_id + "/" + pid + ": P1 accepted evidence absent")
    if after_total < 10:
        errors.append("P1.7 fails established 10/11 positive-probe floor")
    if total != 11 or len(keys) != 3:
        errors.append("P1.7 requires the unchanged original three-fixture 11-probe corpus")

    result = {
        "schema": SCHEMA,
        "status": "failed" if errors else (
            "accepted" if after_total == total
            else "accepted_with_known_delivery_gap"
        ),
        "analyzer_revision": analyzer_revision,
        "oracle": {
            "manifest_git_blob": FROZEN_MANIFEST_GIT_BLOB,
            "baseline_git_blob": FROZEN_BASELINE_GIT_BLOB,
            "source": "P1.1a frozen positive-only development cases",
            "revisions_verified_per_fixture": not any(
                "revision" in error or "repository" in error
                for error in errors
            ),
        },
        "totals": {
            "fixtures": len(keys), "source_authored_positive_probes": total,
            "baseline_met": before_total, "current_met": after_total,
            "baseline_unmet": total - before_total,
            "current_unmet": total - after_total,
            "newly_recovered": len(recovered),
            "regressed": len(regressed),
            "still_unmet_from_baseline": len(still_unmet),
            "recovered_probe_ids": recovered,
            "regressed_probe_ids": regressed,
            "still_unmet_probe_ids": still_unmet,
            "positive_probe_coverage_before": (
                "%s/%s" % (before_total, total)
            ),
            "positive_probe_coverage_after": (
                "%s/%s" % (after_total, total)
            ),
        },
        "fixtures": replay_rows,
        "negative_control_evidence": {
            "scope": (
                "Fixed named-route/Blueprint wrong-target controls and "
                "AppConfig hub isolation are directly rechecked above. "
                "Framework dynamic/ambiguous negative fixtures, "
                "frozen-contract conformance and error paths run in pytest."
            ),
            "false_positive_count": None,
            "false_positive_rate": None,
            "reason_not_scorable": (
                "This frozen eleven-probe manifest contains positive "
                "expectations, not an independently labeled set of negative "
                "predictions; passing synthetic negative fixtures does not "
                "estimate field precision or agent-level false-positive rate."
            ),
        },
        "limitations": [
            "This is a known development regression set, not the sealed S7 held-out agent benchmark.",
            "Single-run elapsed time and process RSS are descriptive; no speed/accuracy tradeoff is inferred.",
            "Supported static, inferred framework and verified runtime evidence must not be conflated.",
            "Unmatched contracts and missing static routes are not automatically defects.",
            "The DRF serializer delivery gap remains explicitly tracked until the P2 context policy.",
        ],
        "errors": errors,
    }
    return result


def summary_markdown(result: Mapping[str, Any]) -> str:
    t = result.get("totals") or {}
    lines = [
        "# P1.7 frozen external replay — %s" % result.get("status", "failed"),
        "",
        "Frozen source-authored development positives: **%s -> %s**, "
        "**%s recovered**, **%s regressed**; %s still unmet." % (
            t.get("positive_probe_coverage_before", "unknown"),
            t.get("positive_probe_coverage_after", "unknown"),
            t.get("newly_recovered", "?"), t.get("regressed", "?"),
            t.get("current_unmet", "?"),
        ),
        "",
        "| Pinned fixture | Baseline | Current | Baseline -> current edges | "
        "Analysis ms before -> after | RSS KB before -> after |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for entry in result.get("fixtures", []):
        metrics = entry.get("metrics") or {}
        before, after = metrics.get("baseline") or {}, metrics.get("current") or {}
        lines.append(
            "| %s | %s/%s | %s/%s | %s -> %s | %s -> %s | %s -> %s |" % (
                entry["id"], entry.get("baseline_probes_met"), entry["probe_count"],
                entry.get("current_probes_met"), entry["probe_count"],
                before.get("edges"), after.get("edges"),
                before.get("analysis_elapsed_ms"), after.get("analysis_elapsed_ms"),
                before.get("process_peak_rss_kb"), after.get("process_peak_rss_kb"),
            )
        )
    lines.extend([
        "",
        "Known DRF serializer distinction: the pinned Field implementation is "
        "now activated from a source-proven relation, but the current "
        "minimal-context delivery still omits fields.py (P2).",
        "",
        "**Precision / false-positive rate: unmeasured.** These 11 labels "
        "are positive-only; source-negative synthetic tests are regression "
        "controls, not independently held-out specificity measurements.",
        "",
    ])
    if result.get("errors"):
        lines.extend(["**Acceptance failures:**", ""])
        lines.extend("- " + message for message in result["errors"])
    else:
        lines.append("**Acceptance: PASS** (immutable oracle, source evidence "
                     "tiers, P1.2-P1.6 regressions, diagnostic consistency).")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--reports-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--analyzer-revision", default="unknown")
    args = parser.parse_args(argv)
    output = Path(args.output)
    markdown = Path(args.markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    try:
        manifest_bytes = Path(args.manifest).read_bytes()
        baseline_bytes = Path(args.baseline).read_bytes()
        if git_blob_sha(manifest_bytes) != FROZEN_MANIFEST_GIT_BLOB:
            raise ValueError("the P1.1a manifest blob differs from the frozen oracle")
        if git_blob_sha(baseline_bytes) != FROZEN_BASELINE_GIT_BLOB:
            raise ValueError("the P1.1b baseline blob differs from the frozen oracle")
        manifest = json.loads(manifest_bytes)
        baseline = json.loads(baseline_bytes)
        reports: Dict[str, Mapping[str, Any]] = {}
        for file in sorted(Path(args.reports_dir).glob("p1-*.json")):
            payload = json.loads(file.read_text(encoding="utf-8"))
            fixture_id = payload.get("fixture_id")
            if not fixture_id or fixture_id in reports:
                raise ValueError("missing/duplicated fixture id in " + str(file))
            reports[fixture_id] = payload
        result = compare_replay(
            manifest, baseline, reports, analyzer_revision=args.analyzer_revision,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        result = {
            "schema": SCHEMA, "status": "failed",
            "analyzer_revision": args.analyzer_revision,
            "totals": {},
            "fixtures": [],
            "errors": ["integrity/error-path: %s: %s" % (type(exc).__name__, exc)],
        }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    markdown.write_text(summary_markdown(result), encoding="utf-8")
    print(summary_markdown(result))
    return 0 if result["status"].startswith("accepted") else 1


if __name__ == "__main__":
    sys.exit(main())
