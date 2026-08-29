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


def test_self_analysis_exposes_current_semantic_blind_spots():
    graph = FeynMapEngine().analyze(str(REPO_ROOT), language="python", framework="none")
    report = SelfAnalysisBenchmark(graph, load_golden()).report()

    assert "python_unresolved_call_count" in report["metrics"]
    assert "python_nodes_with_unresolved_calls" in report["metrics"]
    assert "architecture_score" in report["evaluation"]
    assert report["evaluation"]["architecture_score"] >= 0.0
    assert report["evaluation"]["architecture_score"] <= 1.0


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
