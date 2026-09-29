"""P1.1b external framework baseline runner (report known gaps; do not fix them).

Use only the source-authored expectations in the immutable P1.1a manifest.
Check out a public repository at its exact pinned SHA, run current FeynMap,
then capture graph facts, missing relationships, retrieval and diagnostics.

This baseline is NOT a held-out model-repair benchmark and must not silently
modify expectations when a probe fails. Third-party dependencies are never
installed or executed: FeynMap statically analyzes the checked-out sources.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .adapters.javascript import JavaScriptAdapter
from .context_pipeline import SparseContextPipeline
from .engine import FeynMapEngine
from .core import EdgeKind, EvidenceKind
from .integration import contracts
from .minimal_context import MinimalContextBudget
from .query import FeynMapQuery
from .routing import RegionIndex


BASELINE_SCHEMA = "feynmap.p1_external_baseline.v1"
MANIFEST_SCHEMA = "feynmap.external_framework_baseline.v1"


def _path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _node_path(node) -> str:
    return _path(node.location.path) if node.location else ""


def _matching_nodes(graph, path: str, symbol: Optional[str] = None):
    normalized = _path(path)
    return [
        node for node in graph.nodes
        if _node_path(node) == normalized
        and (symbol is None or node.name == symbol)
    ]


def _node_record(node) -> Dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "kind": node.kind.value,
        "language": node.language,
        "file": _node_path(node),
        "line": node.location.line if node.location else None,
        "confidence_tier": node.confidence_tier.value,
    }


def _edge_record(graph, edge) -> Dict[str, Any]:
    target = graph.node(edge.target)
    return {
        "id": edge.id,
        "source_id": edge.source,
        "target_id": edge.target,
        "target_file": _node_path(target) if target is not None else None,
        "target_name": target.name if target is not None else None,
        "kind": edge.kind.value,
        "confidence": edge.confidence,
        "confidence_tier": edge.confidence_tier.value,
        "detectors": [item.detector for item in edge.evidence],
    }


def _source_probes(graph, probe: Mapping[str, Any]) -> Dict[str, Any]:
    source = _matching_nodes(
        graph, str(probe["source_file"]), str(probe["source_symbol"])
    )
    # A named Django URL is *registered* in urls.py, but its SemanticNode is
    # the actual handler in a sibling views.py (or views package). P1.1a
    # records the registration file, not a fictional handler node inside it.
    # Resolve only the uniquely named handler in that application's directory.
    if (
        not source
        and probe["category"] == "http_route"
        and probe.get("expected_target")
    ):
        registration = _path(probe["source_file"])
        app_parent = str(Path(registration).parent).replace("\\", "/")
        source = [
            node for node in graph.nodes
            if node.name == probe["source_symbol"]
            and _node_path(node) != registration
            and (
                app_parent == "."
                or _node_path(node).startswith(app_parent + "/")
            )
            and node.kind.value in {"handler", "class"}
        ]
    result: Dict[str, Any] = {
        "source_nodes": [_node_record(item) for item in source],
        "source_node_count": len(source),
        "source_registration_file": (
            _path(probe["source_file"])
            if probe["category"] == "http_route" and probe.get("expected_target")
            else None
        ),
        "observed_edges": [],
        "observed_contracts": [],
        "status": "unmeasured",
        "passed": False,
    }
    if not source:
        result["status"] = "source_symbol_absent"
        result["source_file_nodes"] = [
            _node_record(node)
            for node in graph.nodes if _node_path(node) == _path(probe["source_file"])
        ][:25]
        return result
    if len(source) != 1:
        result["status"] = "source_symbol_ambiguous"
        return result
    owner = source[0]
    result["observed_contracts"] = list(contracts(owner))[:20]
    result["observed_edges"] = [
        _edge_record(graph, edge)
        for edge in graph.outgoing(owner.id)
        if graph.node(edge.target) is not None
    ][:40]

    category = probe["category"]
    if category in {"framework_relationship", "framework_inference"}:
        expected_targets = _matching_nodes(
            graph,
            str(probe["target_file"]),
            str(probe["target_symbol"]) if probe.get("target_symbol") else None,
        )
        result["target_nodes"] = [_node_record(item) for item in expected_targets[:12]]
        if not expected_targets:
            result["status"] = "target_symbol_or_template_absent"
            return result
        target_ids = {item.id for item in expected_targets}
        expected_kinds = (
            {"renders"} if probe["relationship"] == "renders_template"
            else {"uses_data", "depends_on", "reads", "writes"}
        )
        matched_edges = [
            edge for edge in graph.outgoing(owner.id)
            if edge.target in target_ids and edge.kind.value in expected_kinds
        ]
        result["matching_edges"] = [
            _edge_record(graph, item) for item in matched_edges
        ]
        if matched_edges:
            result["status"] = "matched_relationship"
            result["passed"] = True
        elif probe["relationship"] == "renders_template" and any(
            item.get("kind") == "template_render"
            and (
                str(item.get("target") or "") == _path(probe["target_file"])
                or _path(probe["target_file"]).endswith("/" + _path(item.get("target") or ""))
            )
            for item in contracts(owner)
        ):
            result["status"] = "contract_without_resolved_edge"
        else:
            result["status"] = "missing_relationship"
        return result

    if category == "http_route" and probe.get("expected_path"):
        expected_path = str(probe["expected_path"]).rstrip("/") or "/"
        method = str(probe["expected_method"]).upper()
        server = contracts(owner, "http_server")
        result["observed_contracts"] = server
        path_matches = [
            item for item in server
            if (str(item.get("target") or "").rstrip("/") or "/") == expected_path
        ]
        path_and_method_matches = [
            item for item in path_matches
            if method in {
                str(value).upper() for value in (
                    item.get("methods") or [item.get("method") or "GET"]
                )
            } or "ANY" in {
                str(value).upper() for value in (
                    item.get("methods") or [item.get("method") or "GET"]
                )
            }
        ]
        result["status"] = (
            "matched_route" if path_and_method_matches
            else "missing_route_contract" if not server
            else "path_or_method_mismatch"
        )
        result["passed"] = bool(path_and_method_matches)
        return result

    if category == "http_route" and probe.get("expected_target"):
        server = contracts(owner, "http_server")
        expected_name = str(probe["expected_target"])
        name_matches = [
            item for item in server
            if item.get("name") == expected_name
            and item.get("framework") == "django"
            and item.get("derivation") == "django.urls.static_registration"
            and item.get("evidence_kind") == "static"
            and _path(item.get("source_file") or "") == _path(probe["source_file"])
            and (
                not probe.get("source_line")
                or item.get("source_line") == int(probe["source_line"])
            )
        ]
        result["matching_named_contracts"] = name_matches
        result["observed_contracts"] = server
        result["passed"] = bool(name_matches)
        result["status"] = (
            "matched_named_route" if name_matches
            else "route_present_but_name_missing" if server
            else "named_route_missing"
        )
        return result

    result["status"] = "unsupported_probe_category"
    return result


def _file_channel(path: str) -> str:
    file = _path(path).lower()
    parts = file.split("/")
    name = parts[-1]
    if "migrations" in parts:
        return "migration"
    if "tests" in parts or name.startswith("test_") or name in {"test.py", "tests.py"}:
        return "test"
    if any(part in parts for part in ("vendor", "vendors", "third_party", "node_modules")) or name.endswith(".min.js"):
        return "vendor_or_generated"
    return "implementation_or_other"


def _retrieval_probe(graph, probe: Mapping[str, Any]) -> Dict[str, Any]:
    """Use the real runtime pipeline, not an ad hoc lexical file matcher."""

    query = str(probe["query"])
    pipeline = SparseContextPipeline(graph)
    started = time.perf_counter()
    outcome = pipeline.concept(
        query,
        context_budget=MinimalContextBudget(max_tokens=3200, max_nodes=24, max_edges=24),
        seed_limit=8,
        candidate_limit=64,
        max_depth=3,
        beam_width=8,
        max_nodes=64,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    activated = list(outcome.activation.search.hits)
    delivered = [
        graph.node(node_id) for node_id in outcome.context.selected_node_ids
    ]
    delivered = [item for item in delivered if item is not None]
    activated_files = sorted({
        _node_path(hit.node) for hit in activated if _node_path(hit.node)
    })
    delivered_files = sorted({
        _node_path(item) for item in delivered if _node_path(item)
    })
    essential = [_path(path) for path in probe["essential_files"]]
    missing = [path for path in essential if path not in delivered_files]
    route = RegionIndex(graph).route(query, limit=8)
    channels = dict(Counter(_file_channel(_node_path(item)) for item in delivered))
    return {
        "status": "all_essential_delivered" if not missing else "essential_implementation_missing",
        "passed": not missing,
        "query": query,
        "elapsed_ms": round(elapsed_ms, 3),
        "essential_files": essential,
        "missing_essential_files": missing,
        "activated_files": activated_files,
        "delivered_files": delivered_files,
        "activated_node_count": len(activated),
        "delivered_node_count": len(delivered),
        "delivered_channels_by_node_count": channels,
        "delivered_context_tokens": outcome.context.delivered_tokens,
        "delivered_context_sufficient": outcome.context.sufficient,
        "top_activated_nodes": [_node_record(item.node) for item in activated[:15]],
        "delivered_nodes": [_node_record(item) for item in delivered[:30]],
        "region_route": {
            "selected_regions": list(route.selected_regions),
            "candidate_regions": route.candidate_regions,
        },
        "measurement_note": (
            "Channel shares count delivered nodes, not tokens. "
            "No downstream model was called; essential file labels are deliberately coarse."
        ),
    }


def _minified_js_probe(root: Path) -> Dict[str, Any]:
    """Exercise the actual adapter against vendored files at the pinned SHA."""

    minified_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.min.js")
        if ".git" not in path.parts
    )
    if not minified_paths:
        return {
            "status": "no_minified_assets_in_revision",
            "passed": False,
            "minified_assets": [],
            "note": "No vendor file was present; cannot claim the crash regression was exercised.",
        }
    started = time.perf_counter()
    graph = JavaScriptAdapter().analyze(root)
    # validate() overwrites graph.diagnostics in the current graph model.
    # Preserve adapter-specific skip messages *before* structural revalidation.
    warnings = list(graph.diagnostics.get("warnings", []))
    structural = graph.validate()
    if structural.get("errors"):
        raise ValueError("JavaScript adapter produced invalid graph: %s" % structural["errors"])
    skipped = [
        path for path in minified_paths
        if any("skipped minified JavaScript: " + path in warning for warning in warnings)
    ]
    included = sorted(
        {_node_path(node) for node in graph.nodes} & set(minified_paths)
    )
    passed = len(skipped) == len(minified_paths) and not included
    return {
        "status": "minified_assets_skipped_without_crash" if passed else "minified_skip_incomplete",
        "passed": passed,
        "minified_assets": minified_paths,
        "skipped_assets": skipped,
        "incorrectly_included_assets": included,
        "javascript_adapter_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "javascript_graph_nodes": len(graph.nodes),
        "javascript_warnings": warnings[:12],
        "note": "Static adapter run on pinned source; third-party JS was not executed.",
    }


def _mdn_app_config_impact_probe(graph) -> Dict[str, Any]:
    """Pin P1.3's actual impact/locality outcomes to MDN's existing graph facts."""

    model = _matching_nodes(graph, "catalog/models.py", "Book")
    views = [
        node
        for symbol in ("BookListView", "BookDetailView")
        for node in _matching_nodes(graph, "catalog/views.py", symbol)
    ]
    configs = _matching_nodes(graph, "catalog/apps.py", "CatalogConfig")
    if len(model) != 1 or len(views) != 2 or len(configs) != 1:
        return {
            "status": "missing_external_impact_anchor",
            "passed": False,
            "model_node_count": len(model),
            "view_node_count": len(views),
            "config_node_count": len(configs),
        }
    query = FeynMapQuery(graph)
    model_impact = query.impact(model[0].id, depth=1)
    config_impact = query.impact(configs[0].id, depth=1)
    model_ids = {item["id"] for item in model_impact["nodes"]}
    config_ids = {item["id"] for item in config_impact["nodes"]}
    index = RegionIndex(graph, native_routing=False)
    config_region = index.region_for_node(configs[0].id)
    locality_leaks = [
        view.name for view in views
        if config_region in index.adjacency[index.region_for_node(view.id)]
    ]
    actual_model_views = sorted(view.name for view in views if view.id in model_ids)
    bad_config_views = sorted(view.name for view in views if view.id in config_ids)
    passed = (
        len(actual_model_views) == 2
        and not bad_config_views
        and not locality_leaks
    )
    return {
        "status": "grounded_impact_without_appconfig_hub" if passed else "impact_or_locality_regression",
        "passed": passed,
        "model_impact_views": actual_model_views,
        "incorrect_config_impact_views": bad_config_views,
        "incorrect_config_region_neighbors": locality_leaks,
        "model_path": "catalog/models.py",
        "app_config_path": "catalog/apps.py",
        "depth": 1,
    }


def _graph_summary(graph) -> Dict[str, Any]:
    channels = Counter(node.language or "unknown" for node in graph.nodes)
    kinds = Counter(edge.kind.value for edge in graph.edges)
    contracts_by_kind = Counter(
        item.get("kind") or "unknown"
        for node in graph.nodes for item in contracts(node)
    )
    app_config_edges = [
        edge for edge in graph.edges
        if (
            edge.attributes.get("framework", {}).get("relationship") == "app_config"
            if isinstance(edge.attributes.get("framework"), dict) else False
        )
    ]
    structural = graph.metadata.get("django_app_membership") or {}
    memberships = structural.get("associations", []) if isinstance(structural, dict) else []
    # Keep the historical *edge* diagnostic separately: after P1.3 this
    # should be zero while the inferred app-membership observations remain.
    hubs = Counter(
        item["app_config_node_id"] for item in memberships
        if isinstance(item, dict) and item.get("app_config_node_id")
    )
    integration = graph.metadata.get("integration") or {}
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "nodes_by_language": dict(sorted(channels.items())),
        "edges_by_kind": dict(sorted(kinds.items())),
        "contracts_by_kind": dict(sorted(contracts_by_kind.items())),
        "app_config_membership_edges": len(app_config_edges),
        "app_config_source_membership_count": len(memberships),
        "app_config_membership_unresolved_count": len(
            structural.get("unresolved", []) if isinstance(structural, dict) else []
        ),
        "app_config_target_hubs": [
            {"node_id": node_id, "handler_count": count}
            for node_id, count in hubs.most_common(10)
        ],
        "integration_resolved_edges": integration.get("resolved_edges"),
        "unresolved_contract_count": integration.get("unresolved_contracts"),
        "unresolved_sample": list(integration.get("unresolved_sample") or [])[:25],
        "integration_diagnostics_v2": integration.get("diagnostics_v2") or {},
        "django_drf_stats": (
            (graph.metadata.get("django_drf") or {}).get("stats") or {}
        ),
        "django_drf_unresolved_count": len(
            (graph.metadata.get("django_drf") or {}).get("unresolved") or []
        ),
        "django_drf_route_coverage_count": len(
            (graph.metadata.get("django_drf") or {}).get("route_coverage") or []
        ),
        "diagnostics": {
            "error_count": len(graph.diagnostics.get("errors", [])),
            "warning_count": len(graph.diagnostics.get("warnings", [])),
            "errors": list(graph.diagnostics.get("errors", []))[:25],
            "warnings": list(graph.diagnostics.get("warnings", []))[:25],
        },
        "framework_adapter": graph.metadata.get("framework_adapter"),
        "analysis_contract_version": graph.metadata.get("analysis_contract_version"),
    }



def _drf_field_type_source_probe(graph) -> Dict[str, Any]:
    """Acceptance needs the actual DRF metaclass->Field usage, not any edge."""
    method = [
        node for node in graph.nodes
        if node.qualified_name ==
        "rest_framework.serializers.SerializerMetaclass._get_declared_fields"
    ]
    field = [
        node for node in graph.nodes
        if node.qualified_name == "rest_framework.fields.Field"
    ]
    matches = []
    if len(method) == 1 and len(field) == 1:
        matches = [
            edge for edge in graph.outgoing(method[0].id)
            if edge.target == field[0].id
            and edge.kind == EdgeKind.USES_DATA
            and edge.attributes.get("framework", {}).get("relationship")
                == "drf_declared_field_type_check"
            and any(
                evidence.kind == EvidenceKind.STATIC
                and evidence.detector ==
                    "django.drf.serializer_metaclass_field_type_check"
                and evidence.location is not None
                and evidence.location.path == "rest_framework/serializers.py"
                for evidence in edge.evidence
            )
        ]
    return {
        "status": "grounded_source_usage" if len(matches) == 1
                  else "missing_or_ambiguous_source_usage",
        "passed": len(matches) == 1,
        "metaclass_method_count": len(method),
        "field_target_count": len(field),
        "source_evidenced_edge_count": len(matches),
        "source_file": "rest_framework/serializers.py",
        "target_file": "rest_framework/fields.py",
        "source_expression": "isinstance(obj, Field)",
    }


def evaluate_fixture(
    fixture: Mapping[str, Any],
    project_root: Path,
    *,
    actual_commit: str,
) -> Dict[str, Any]:
    expected_sha = str(fixture["commit"])
    if actual_commit != expected_sha:
        raise ValueError(
            "pinned checkout mismatch for %s: expected %s, got %s"
            % (fixture["id"], expected_sha, actual_commit)
        )
    started = time.perf_counter()
    graph = FeynMapEngine().analyze(
        str(project_root),
        language="auto",
        framework=str(fixture["framework"]),
    )
    graph.validate()
    analysis_ms = (time.perf_counter() - started) * 1000.0
    # Linux GitHub Actions ru_maxrss uses kilobytes; per fixture runs in its
    # own process, so the high-water mark is not contaminated by prior repos.
    try:
        import resource
        peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        peak_rss_kb = None

    probes = []
    for probe in fixture["probes"]:
        if probe["category"] in {"framework_relationship", "framework_inference", "http_route"}:
            observed = _source_probes(graph, probe)
        elif probe["category"] == "retrieval":
            observed = _retrieval_probe(graph, probe)
        elif probe["category"] == "ingestion":
            observed = _minified_js_probe(project_root)
        else:
            raise ValueError("unsupported probe category: %s" % probe["category"])
        probes.append({
            "id": probe["id"],
            "category": probe["category"],
            "expected_status": probe["expected_status"],
            "observed": observed,
            "passed": observed["passed"],
        })
    result = {
        "schema": BASELINE_SCHEMA,
        "status": "analyzed_with_gaps" if any(not p["passed"] for p in probes) else "all_probes_met",
        "fixture_id": fixture["id"],
        "repository": fixture["repository"],
        "expected_commit": expected_sha,
        "actual_commit": actual_commit,
        "analysis_elapsed_ms": round(analysis_ms, 3),
        "process_peak_rss_kb": peak_rss_kb,
        "graph": _graph_summary(graph),
        "probe_count": len(probes),
        "matched_probes": sum(p["passed"] for p in probes),
        "missing_probes": [p["id"] for p in probes if not p["passed"]],
        "probes": probes,
        "p1_6_drf_field_usage": (
            _drf_field_type_source_probe(graph)
            if fixture["id"] == "django-rest-framework" else None
        ),
        "p1_3_django_impact": (
            _mdn_app_config_impact_probe(graph)
            if fixture["id"] == "mdn-django-local-library" else None
        ),
        "baseline_only": True,
        "no_parser_semantics_changed": True,
    }
    return result


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate pinned P1.1b external repository with unchanged FeynMap"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture_id = args.fixture
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("unexpected P1.1 manifest version")
        fixture = next(
            item for item in manifest["fixtures"] if item["id"] == fixture_id
        )
        root = Path(args.project_root).resolve()
        actual_commit = _git_sha(root)
        report = evaluate_fixture(fixture, root, actual_commit=actual_commit)
        exit_code = 0
    except Exception as exc:
        report = {
            "schema": BASELINE_SCHEMA,
            "status": "analysis_error",
            "fixture_id": fixture_id,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diagnostic = {
        key: report[key]
        for key in ("fixture_id", "status", "analysis_elapsed_ms", "probe_count",
                    "matched_probes", "missing_probes", "error")
        if key in report
    }
    if "probes" in report:
        diagnostic["observed_probes"] = [
            {
                "id": item["id"],
                "status": item["observed"]["status"],
                "source_node_count": item["observed"].get("source_node_count"),
                "source_file_node_names": [
                    node["name"] for node in item["observed"].get("source_file_nodes", [])
                ],
                "actual_routes": [
                    {
                        "target": row.get("target"),
                        "methods": row.get("methods"),
                        "name": row.get("name"),
                        "source_file": row.get("source_file"),
                    }
                    for row in item["observed"].get("observed_contracts", [])
                    if row.get("kind") == "http_server"
                ],
                "missing_essential_files": item["observed"].get("missing_essential_files"),
                "activated_files": item["observed"].get("activated_files"),
                "activated_top": [
                    (node.get("file"), node.get("name"))
                    for node in item["observed"].get("top_activated_nodes", [])[:12]
                ],
                "delivered_top": [
                    (node.get("file"), node.get("name"))
                    for node in item["observed"].get("delivered_nodes", [])[:24]
                ],
                "delivered_files": item["observed"].get("delivered_files"),
                "delivered_channels": item["observed"].get("delivered_channels_by_node_count"),
                "minified_assets": item["observed"].get("minified_assets"),
                "minified_skipped": item["observed"].get("skipped_assets"),
            }
            for item in report["probes"]
        ]
        diagnostic["app_config_membership_edges"] = report["graph"]["app_config_membership_edges"]
        diagnostic["app_config_source_memberships"] = report["graph"]["app_config_source_membership_count"]
        diagnostic["app_config_membership_unresolved"] = report["graph"]["app_config_membership_unresolved_count"]
        if report.get("p1_3_django_impact") is not None:
            diagnostic["p1_3_django_impact"] = report["p1_3_django_impact"]
        diagnostic["integration_unresolved"] = report["graph"]["unresolved_contract_count"]
        diagnostic["integration_diagnostics_v2"] = {
            key: value for key, value in
            report["graph"]["integration_diagnostics_v2"].items()
            if key.endswith("_count") or key in {
                "counts_by_category", "python_intrinsic_unresolved_calls",
                "python_other_unresolved_calls", "framework_unresolved_observations",
            }
        }
        if report.get("p1_6_drf_field_usage") is not None:
            diagnostic["p1_6_drf_field_usage"] = report["p1_6_drf_field_usage"]
        diagnostic["graph_warnings"] = report["graph"]["diagnostics"]["warnings"][:6]
    print(json.dumps(diagnostic, sort_keys=True))
    # Missing known semantic relationships are the intended baseline result,
    # not a reason to hide the report or mark the analysis runner as broken.
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
