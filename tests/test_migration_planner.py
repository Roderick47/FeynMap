from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.migration import MigrationPlanner


def test_planner_reports_readiness_and_units():
    evidence = [Evidence(EvidenceKind.STATIC, "test", confidence=1.0)]
    graph = SemanticGraph(
        [
            SemanticNode("handler", "Handler", NodeKind.HANDLER, evidence=evidence),
            SemanticNode("service", "Service", NodeKind.SERVICE, evidence=evidence),
            SemanticNode("model", "Model", NodeKind.DATA_MODEL, evidence=evidence),
        ],
        [
            SemanticEdge("e1", "handler", "service", EdgeKind.CALLS, 0.98, evidence),
            SemanticEdge("e2", "service", "model", EdgeKind.USES_DATA, 0.96, evidence),
        ],
    )
    plan = MigrationPlanner(graph).plan()
    assert plan["assessment"]["readiness_score"] > 0.9
    assert plan["units"]
    assert set(plan["units"][0]["members"]) == {"handler", "service", "model"}
