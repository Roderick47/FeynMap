from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation


def sample_graph():
    location = SourceLocation("app.py", 10)
    nodes = [
        SemanticNode("handler", "handler", NodeKind.HANDLER, "python", evidence=[Evidence(EvidenceKind.STATIC, "test", location=location, confidence=1.0)]),
        SemanticNode("service", "service", NodeKind.SERVICE, "python", evidence=[Evidence(EvidenceKind.STATIC, "test", location=location, confidence=1.0)]),
    ]
    edges = [SemanticEdge("e1", "handler", "service", EdgeKind.CALLS, 1.0, [Evidence(EvidenceKind.STATIC, "test", location=location, confidence=1.0)])]
    return SemanticGraph(nodes, edges)


def test_graph_serializes_with_evidence_and_schema():
    payload = sample_graph().to_dict()
    assert payload["schema"] == "feynmap.semantic_graph"
    assert payload["metadata"]["evidence_coverage"] == 1.0
    assert payload["nodes"][0]["confidence_tier"] == "verified"
    assert payload["edges"][0]["kind"] == "calls"


def test_graph_find_and_indexes():
    graph = sample_graph()
    assert graph.find("handler")[0].id == "handler"
    assert graph.outgoing("handler")[0].target == "service"
    assert graph.incoming("service")[0].source == "handler"
