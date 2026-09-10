from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.query import FeynMapQuery
import pytest


def test_duplicate_names_require_qualified_name_or_id():
    api = FeynMapQuery(SemanticGraph([
        SemanticNode("a", "run", NodeKind.FUNCTION, qualified_name="first.run"),
        SemanticNode("b", "run", NodeKind.FUNCTION, qualified_name="second.run"),
        SemanticNode("c", "runner", NodeKind.FUNCTION, qualified_name="third.runner"),
    ], []))
    with pytest.raises(KeyError, match="ambiguous"):
        api.resolve("run")
    assert api.resolve("first.run").id == "a"
    assert api.resolve("b").id == "b"
    assert api.resolve("runner").id == "c"


def test_exact_qualified_name_wins_over_partial_matches():
    api = FeynMapQuery(SemanticGraph([
        SemanticNode("a", "run", NodeKind.FUNCTION, qualified_name="app.run"),
        SemanticNode("b", "run_more", NodeKind.FUNCTION, qualified_name="app.run_more"),
    ], []))
    assert api.resolve("app.run").id == "a"


def graph():
    evidence = [Evidence(EvidenceKind.STATIC, "test", confidence=1.0)]
    return SemanticGraph(
        [
            SemanticNode("view", "PaymentView", NodeKind.HANDLER, evidence=evidence),
            SemanticNode("service", "PaymentService", NodeKind.SERVICE, evidence=evidence),
            SemanticNode("model", "Payment", NodeKind.DATA_MODEL, evidence=evidence),
        ],
        [
            SemanticEdge("e1", "view", "service", EdgeKind.CALLS, 1.0, evidence),
            SemanticEdge("e2", "service", "model", EdgeKind.USES_DATA, 0.95, evidence),
        ],
    )


def test_context_bundle_walks_both_directions():
    api = FeynMapQuery(graph())
    bundle = api.context_bundle("PaymentService", depth=1)
    assert bundle["symbol"]["id"] == "service"
    assert {node["id"] for node in bundle["dependencies"]["nodes"]} == {"model"}
    assert {node["id"] for node in bundle["callers"]["nodes"]} == {"view"}


def test_claim_validation_is_conservative():
    api = FeynMapQuery(graph())
    supported = api.validate_claim("PaymentView", "PaymentService", "calls")
    assert supported["supported"] is True
    assert supported["status"] == "supported"
    unsupported = api.validate_claim("PaymentView", "Payment", "calls")
    assert unsupported["supported"] is False
    assert "does not prove" in unsupported["note"]


def test_callers_exclude_containment_but_impact_keeps_broad_closure():
    g = graph()
    g.add_edge(SemanticEdge('contains', 'model', 'service', EdgeKind.CONTAINS, 1))
    api = FeynMapQuery(g)
    assert {n['id'] for n in api.callers('service')['nodes']} == {'view'}
    assert {n['id'] for n in api.impact('service', depth=1)['nodes']} == {'view', 'model'}
    assert api.callers('service')['relationship_filter'] == ['calls', 'invokes']
