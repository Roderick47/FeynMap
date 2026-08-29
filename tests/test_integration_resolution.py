from feynmap import EdgeKind
from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import IntegrationResolver, add_contract


def test_unresolved_contracts_are_tracked_individually():
    client = SemanticNode("client", "client", NodeKind.FUNCTION, language="javascript")
    health = SemanticNode("health", "health", NodeKind.HANDLER, language="python")

    add_contract(client, "http_client", "/health", method="GET")
    add_contract(client, "http_client", "/missing", method="POST")
    add_contract(health, "http_server", "/health", methods=["GET"])

    graph = SemanticGraph(nodes=[client, health])
    IntegrationResolver().resolve(graph)

    assert any(edge.kind == EdgeKind.REQUESTS and edge.source == client.id and edge.target == health.id for edge in graph.edges)
    assert graph.metadata["integration"]["unresolved_contracts"] == 1
    assert graph.metadata["integration"]["unresolved_sample"][0]["target"] == "/missing"


def test_ambiguous_server_matches_do_not_create_guessed_edges():
    client = SemanticNode("client", "client", NodeKind.FUNCTION, language="javascript")
    server_a = SemanticNode("a", "server_a", NodeKind.HANDLER, language="python")
    server_b = SemanticNode("b", "server_b", NodeKind.HANDLER, language="rust")

    add_contract(client, "http_client", "/status", method="GET")
    add_contract(server_a, "http_server", "/status", methods=["GET"])
    add_contract(server_b, "http_server", "/status", methods=["GET"])

    graph = SemanticGraph(nodes=[client, server_a, server_b])
    IntegrationResolver().resolve(graph)

    assert not any(edge.kind == EdgeKind.REQUESTS for edge in graph.edges)
    assert graph.metadata["integration"]["unresolved_contracts"] >= 1
