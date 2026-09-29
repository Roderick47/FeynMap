"""P1.7: immutable positive-only acceptance, evidence and error-path tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from feynmap.p1_replay_acceptance import (
    FROZEN_BASELINE_GIT_BLOB, FROZEN_MANIFEST_GIT_BLOB,
    compare_replay, git_blob_sha, main, summary_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "experiments/p1_external_framework_manifest.json"
BASELINE_PATH = ROOT / "experiments/results/p1_1b_20260929_external_baseline.json"


def _locked():
    return (json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
            json.loads(BASELINE_PATH.read_text(encoding="utf-8")))


def _report(spec):
    rows = []
    for probe in spec["probes"]:
        pid = probe["id"]
        passed = pid != "serializer-implementation-recall"
        if probe["category"] in {"framework_relationship", "framework_inference"}:
            tier = ("inferred" if probe["category"] == "framework_inference"
                    else "supported")
            observed = {
                "passed": passed, "status": "matched_relationship",
                "matching_edges": [{
                    "confidence_tier": tier,
                    "kind": ("renders" if probe["relationship"] == "renders_template"
                             else "uses_data"),
                    "detectors": ["source_or_framework_evidence"],
                }],
            }
        elif pid == "named-url-books":
            observed = {
                "passed": passed, "status": "matched_named_route",
                "matching_named_contracts": [{
                    "target": "/catalog/books/", "name": "books",
                    "framework": "django",
                    "source_file": "catalog/urls.py", "source_line": 8,
                    "derivation": "django.urls.static_registration",
                    "evidence_kind": "static",
                }],
            }
        elif probe["category"] == "http_route":
            observed = {
                "passed": passed, "status": "matched_route",
                "observed_contracts": [{
                    "kind": "http_server", "target": "/api/tokens",
                    "methods": [probe["expected_method"]],
                    "source_file": "app/api/tokens.py",
                    "source_line": probe["route_line"],
                    "registration_file": "app/__init__.py",
                    "blueprint_declaration_file": "app/api/__init__.py",
                    "blueprint_id": "app.api.bp",
                    "derivation": "flask.blueprint.registered_route",
                    "evidence_kind": "static",
                }],
            }
        elif pid == "throttling-implementation-recall":
            observed = {
                "passed": passed, "status": "all_essential_delivered",
                "activated_files": ["rest_framework/throttling.py"],
                "delivered_files": ["rest_framework/throttling.py"],
                "delivered_channels_by_node_count": {
                    "implementation_or_other": 10, "test": 1,
                },
                "activated_node_count": 16, "delivered_node_count": 11,
                "delivered_context_tokens": 1200,
            }
        elif pid == "serializer-implementation-recall":
            observed = {
                "passed": False, "status": "essential_implementation_missing",
                "activated_files": ["rest_framework/serializers.py",
                                    "rest_framework/fields.py"],
                "delivered_files": ["rest_framework/serializers.py",
                                    "tests/test_validation.py"],
                "missing_essential_files": ["rest_framework/fields.py"],
                "activated_node_count": 45, "delivered_node_count": 14,
                "delivered_context_tokens": 3000,
                "delivered_channels_by_node_count": {
                    "implementation_or_other": 2, "test": 12,
                },
            }
        elif pid == "vendored-js-no-crash":
            observed = {
                "passed": passed,
                "status": "minified_assets_skipped_without_crash",
                "minified_assets": ["bootstrap.min.js", "jquery.min.js"],
                "skipped_assets": ["bootstrap.min.js", "jquery.min.js"],
            }
        else:
            raise AssertionError("fixture manifest unexpectedly expanded")
        rows.append({
            "id": pid, "category": probe["category"],
            "expected_status": probe["expected_status"],
            "passed": passed, "observed": observed,
        })
    fixture_id = spec["id"]
    raw_unmatched = {"mdn-django-local-library": 20,
                     "grinberg-microblog": 30,
                     "django-rest-framework": 54}[fixture_id]
    review = 18 if fixture_id == "django-rest-framework" else 0
    return {
        "schema": "feynmap.p1_external_baseline.v1",
        "fixture_id": fixture_id, "repository": spec["repository"],
        "expected_commit": spec["commit"], "actual_commit": spec["commit"],
        "status": "analyzed_with_gaps" if any(not p["passed"] for p in rows)
                  else "all_probes_met",
        "probe_count": len(rows),
        "matched_probes": sum(row["passed"] for row in rows),
        "missing_probes": [row["id"] for row in rows if not row["passed"]],
        "probes": rows,
        "analysis_elapsed_ms": 1500,
        "process_peak_rss_kb": 39000,
        "graph": {
            "nodes": 4128 if fixture_id == "django-rest-framework" else 266,
            "edges": 8113 if fixture_id == "django-rest-framework" else 675,
            "app_config_membership_edges": 0,
            "app_config_source_membership_count": {
                "mdn-django-local-library": 29,
                "grinberg-microblog": 0,
                "django-rest-framework": 20,
            }[fixture_id],
            "unresolved_contract_count": raw_unmatched,
            "diagnostics": {"error_count": 0},
            "integration_diagnostics_v2": {
                "raw_unmatched_contract_count": raw_unmatched,
                "classified_unmatched_contract_count": raw_unmatched,
                "counts_by_category": {
                    "local_static_target_requires_review": review,
                    "unknown_or_non_peer_contract": raw_unmatched - review,
                },
                "actionable_review_candidate_count": review,
                "non_actionable_or_unproven_count": raw_unmatched - review,
            },
        },
        "p1_3_django_impact": (
            {"passed": True} if fixture_id == "mdn-django-local-library" else None
        ),
        "p1_6_drf_field_usage": ({
            "passed": True, "metaclass_method_count": 1,
            "field_target_count": 1, "source_evidenced_edge_count": 1,
            "source_file": "rest_framework/serializers.py",
            "target_file": "rest_framework/fields.py",
        } if fixture_id == "django-rest-framework" else None),
    }


def _expected():
    manifest, baseline = _locked()
    return manifest, baseline, {
        fixture["id"]: _report(fixture) for fixture in manifest["fixtures"]
    }


def test_frozen_oracle_git_blobs_match_preexisting_p1_artifacts():
    assert git_blob_sha(MANIFEST_PATH.read_bytes()) == FROZEN_MANIFEST_GIT_BLOB
    assert git_blob_sha(BASELINE_PATH.read_bytes()) == FROZEN_BASELINE_GIT_BLOB
    assert git_blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_replay_retains_p1_truth_and_leaves_unmeasured_precision_unknown():
    manifest, baseline, reports = _expected()
    original_manifest_bytes = MANIFEST_PATH.read_bytes()
    original_baseline_bytes = BASELINE_PATH.read_bytes()
    result = compare_replay(
        manifest, baseline, reports, analyzer_revision="synthetic-control",
    )
    assert result["status"] == "accepted_with_known_delivery_gap", result["errors"]
    assert result["errors"] == []
    assert result["totals"]["positive_probe_coverage_before"] == "2/11"
    assert result["totals"]["positive_probe_coverage_after"] == "10/11"
    assert result["totals"]["newly_recovered"] == 8
    assert result["totals"]["regressed"] == 0
    assert result["totals"]["still_unmet_from_baseline"] == 1
    assert result["negative_control_evidence"]["false_positive_count"] is None
    assert result["negative_control_evidence"]["false_positive_rate"] is None
    assert MANIFEST_PATH.read_bytes() == original_manifest_bytes
    assert BASELINE_PATH.read_bytes() == original_baseline_bytes
    drf = next(item for item in result["fixtures"]
               if item["id"] == "django-rest-framework")
    serializer = next(row for row in drf["probes"]
                      if row["id"] == "serializer-implementation-recall")
    assert serializer["context"]["current_activated_essential_count"] == 2
    assert serializer["context"]["current_delivered_essential_count"] == 1
    assert serializer["current_met"] is False
    assert drf["metrics"]["baseline"]["edges"] == 8040
    assert drf["metrics"]["current"]["edges"] == 8113
    assert "Precision / false-positive rate: unmeasured" in summary_markdown(result)


@pytest.mark.parametrize("probe_id", [
    "throttling-implementation-recall", "vendored-js-no-crash",
])
def test_original_passing_evidence_must_not_regress(probe_id):
    manifest, baseline, reports = _expected()
    report = reports["django-rest-framework"]
    row = next(item for item in report["probes"] if item["id"] == probe_id)
    row["passed"] = False
    row["observed"]["passed"] = False
    report["matched_probes"] -= 1
    report["missing_probes"].append(probe_id)
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert result["totals"]["regressed"] == 1
    assert any("regressed" in issue for issue in result["errors"])


def test_provenance_tier_cannot_be_promoted_from_inferred_to_supported():
    manifest, baseline, reports = _expected()
    row = next(item for item in reports["mdn-django-local-library"]["probes"]
               if item["id"] == "cbv-book-detail-default-template")
    row["observed"]["matching_edges"][0]["confidence_tier"] = "supported"
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert any("evidence tier" in issue for issue in result["errors"])


def test_missing_or_duplicate_or_mutated_positive_probes_fail_integrity():
    for kind in ("missing", "duplicate", "mutated"):
        manifest, baseline, reports = _expected()
        report = reports["grinberg-microblog"]
        if kind == "missing":
            report["probes"].pop()
        elif kind == "duplicate":
            report["probes"].append(copy.deepcopy(report["probes"][0]))
        else:
            report["probes"][0]["expected_status"] = "verified"
        result = compare_replay(manifest, baseline, reports)
        assert result["status"] == "failed", kind


def test_raw_blueprint_fragment_and_missing_field_bridge_are_rejected():
    manifest, baseline, reports = _expected()
    report = reports["grinberg-microblog"]
    report["probes"][0]["observed"]["observed_contracts"].append({
        "kind": "http_server", "target": "/tokens", "methods": ["POST"],
    })
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert any("raw path" in issue for issue in result["errors"])

    manifest, baseline, reports = _expected()
    reports["django-rest-framework"]["p1_6_drf_field_usage"] = {"passed": False}
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert any("SerializerMetaclass Field" in issue for issue in result["errors"])


def test_activation_does_not_masquerade_as_actual_delivery():
    manifest, baseline, reports = _expected()
    report = reports["django-rest-framework"]
    row = next(item for item in report["probes"]
               if item["id"] == "serializer-implementation-recall")
    row["passed"] = True
    row["observed"]["passed"] = True
    report["matched_probes"] += 1
    report["missing_probes"].remove("serializer-implementation-recall")
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert any("delivery score contradicts" in issue for issue in result["errors"])


def test_pinned_revision_and_diagnostic_denominator_must_match():
    manifest, baseline, reports = _expected()
    reports["django-rest-framework"]["actual_commit"] = "0" * 40
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert any("revision" in issue for issue in result["errors"])

    manifest, baseline, reports = _expected()
    d = reports["django-rest-framework"]["graph"]["integration_diagnostics_v2"]
    d["actionable_review_candidate_count"] += 1
    result = compare_replay(manifest, baseline, reports)
    assert result["status"] == "failed"
    assert any("do not reconcile" in issue for issue in result["errors"])


def _stage(tmp_path, manifest, baseline, reports):
    source = tmp_path / "manifest.json"
    initial = tmp_path / "baseline.json"
    folder = tmp_path / "collected"
    folder.mkdir(parents=True, exist_ok=True)
    source.write_bytes(MANIFEST_PATH.read_bytes())
    initial.write_bytes(BASELINE_PATH.read_bytes())
    for identifier, report in reports.items():
        (folder / ("p1-" + identifier + ".json")).write_text(
            json.dumps(report), encoding="utf-8",
        )
    output = tmp_path / "result.json"
    markdown = tmp_path / "result.md"
    argv = [
        "--manifest", str(source), "--baseline", str(initial),
        "--reports-dir", str(folder), "--output", str(output),
        "--markdown", str(markdown), "--analyzer-revision", "example-sha",
    ]
    return source, initial, folder, output, markdown, argv


def test_cli_writes_machine_readable_and_markdown_acceptance(tmp_path):
    manifest, baseline, reports = _expected()
    source, initial, folder, output, markdown, argv = _stage(
        tmp_path, manifest, baseline, reports,
    )
    assert main(argv) == 0
    report = json.loads(output.read_text())
    assert report["status"] == "accepted_with_known_delivery_gap"
    assert report["analyzer_revision"] == "example-sha"
    assert report["totals"]["current_met"] == 10
    assert "# P1.7 frozen external replay" in markdown.read_text()


@pytest.mark.parametrize("corruption", [
    "manifest", "baseline", "duplicate", "missing", "bad_sha",
])
def test_cli_error_path_emits_failure_artifact_not_fake_success(tmp_path, corruption):
    manifest, baseline, reports = _expected()
    source, initial, folder, output, markdown, argv = _stage(
        tmp_path, manifest, baseline, reports,
    )
    if corruption == "manifest":
        source.write_text(source.read_text() + " ", encoding="utf-8")
    elif corruption == "baseline":
        initial.write_text(initial.read_text() + "\n", encoding="utf-8")
    elif corruption == "duplicate":
        file = next(folder.glob("p1-*.json"))
        (folder / "p1-duplicate.json").write_bytes(file.read_bytes())
    elif corruption == "missing":
        next(folder.glob("p1-*.json")).unlink()
    else:
        file = next(folder.glob("p1-*.json"))
        payload = json.loads(file.read_text())
        payload["actual_commit"] = "f" * 40
        file.write_text(json.dumps(payload))
    assert main(argv) == 1
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert report["errors"]
    assert "Acceptance failures" in markdown.read_text()
