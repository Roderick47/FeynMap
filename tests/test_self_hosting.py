from pathlib import Path

from feynmap import EdgeKind, FeynMapEngine
from feynmap.self_hosting import SelfAnalysisBenchmark, load_golden


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_feynmap_can_analyze_its_own_repository():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), framework="none")
    golden = load_golden()
    report = SelfAnalysisBenchmark(graph, golden).report()

    assert report["metrics"]["graph_errors"] == 0
    assert report["metrics"]["node_count"] > 0
    assert report["metrics"]["edge_count"] > 0
    assert report["evaluation"]["expected_symbol_count"] >= 10
    assert report["evaluation"]["missing_symbol_count"] == 0
    assert report["quality_gates"]["gate_count"] == 4
    assert report["quality_gates"]["status"] == "pass"


def test_self_analysis_exposes_current_semantic_blind_spots():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), language="python", framework="none")
    report = SelfAnalysisBenchmark(graph, load_golden()).report()

    assert "python_unresolved_call_count" in report["metrics"]
    assert "python_nodes_with_unresolved_calls" in report["metrics"]
    assert "architecture_score" in report["evaluation"]
    assert report["evaluation"]["architecture_score"] >= 0.0
    assert report["evaluation"]["architecture_score"] <= 1.0
    assert "python_unresolved_call_count" in report["quality_gates"]["deferred_numeric_thresholds"]


def test_golden_architecture_checks_engine_merge_relationship():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), language="python", framework="none")
    report = SelfAnalysisBenchmark(graph, load_golden()).report()

    relationships = report["evaluation"]["relationships"]
    merge_fact = next(
        item
        for item in relationships
        if item["source"] == "feynmap.engine.FeynMapEngine.analyze"
        and item["target"] == "feynmap.repository.merge_language_graphs"
        and item["kind"] == EdgeKind.CALLS.value
    )
    assert merge_fact["found"] is True


def test_first_recursive_improvement_resolves_integration_resolver_call():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), language="python", framework="none")
    report = SelfAnalysisBenchmark(graph, load_golden()).report()
    relationships = report["evaluation"]["relationships"]

    resolver_fact = next(
        item
        for item in relationships
        if item["source"] == "feynmap.engine.FeynMapEngine.analyze"
        and item["target"] == "feynmap.integration.IntegrationResolver.resolve"
        and item["kind"] == EdgeKind.CALLS.value
    )
    assert resolver_fact["found"] is True


def test_feynmap_resolves_its_adapter_reexports_in_default_registry():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), language="python", framework="none")
    report = SelfAnalysisBenchmark(graph, load_golden()).report()
    relationships = report["evaluation"]["relationships"]

    expected_targets = {
        "feynmap.adapters.python.PythonAdapter",
        "feynmap.adapters.html.HTMLAdapter",
        "feynmap.adapters.javascript.JavaScriptAdapter",
        "feynmap.adapters.frameworks.django.DjangoAdapter",
        "feynmap.adapters.frameworks.flask.FlaskAdapter",
        "feynmap.adapters.frameworks.fastapi.FastAPIAdapter",
    }
    adapter_facts = [
        item
        for item in relationships
        if item["source"] == "feynmap.engine.default_registry"
        and item["target"] in expected_targets
        and item["kind"] == EdgeKind.CALLS.value
    ]

    assert {item["target"] for item in adapter_facts} == expected_targets
    assert all(item["found"] is True for item in adapter_facts)

    metadata = graph.metadata["python_reexport_resolution"]
    assert metadata["resolved_aliases"] >= len(expected_targets)
    assert metadata["call_edges_added"] >= len(expected_targets)


def test_feynmap_uses_reexported_registry_type_for_instance_dispatch():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), language="python", framework="none")
    report = SelfAnalysisBenchmark(graph, load_golden()).report()
    relationships = report["evaluation"]["relationships"]

    expected = {
        (
            "feynmap.engine.FeynMapEngine._select_languages",
            "feynmap.adapters.base.AdapterRegistry.detect_languages",
        ),
        (
            "feynmap.engine.FeynMapEngine._select_languages",
            "feynmap.adapters.base.AdapterRegistry.language",
        ),
        (
            "feynmap.engine.FeynMapEngine.analyze",
            "feynmap.adapters.base.AdapterRegistry.detect_frameworks",
        ),
        (
            "feynmap.engine.FeynMapEngine.analyze",
            "feynmap.adapters.base.AdapterRegistry.framework",
        ),
    }
    registry_facts = [
        item
        for item in relationships
        if (item["source"], item["target"]) in expected and item["kind"] == EdgeKind.CALLS.value
    ]

    assert {(item["source"], item["target"]) for item in registry_facts} == expected
    assert all(item["found"] is True for item in registry_facts)

    metadata = graph.metadata["python_attribute_resolution"]
    assert metadata["reexport_aliases_consulted"] >= 1
    assert metadata["alias_grounded_call_edges"] >= len(expected)
