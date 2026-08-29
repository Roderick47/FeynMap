from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.query import FeynMapQuery


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
    assert supported["status"] == "verified"
    unsupported = api.validate_claim("PaymentView", "Payment", "calls")
    assert unsupported["supported"] is False
    assert "does not prove" in unsupported["note"]
