"""P1.6: unmatched contracts are observations, not all actionable defects."""
from feynmap.core import SemanticGraph, SemanticNode, NodeKind, SourceLocation
from feynmap.integration import IntegrationResolver, add_contract


def _node(identifier, name, *, python=False):
    return SemanticNode(
        id=identifier, name=name, qualified_name=name,
        kind=NodeKind.HANDLER if python else NodeKind.MODULE,
        language="python" if python else "javascript",
        location=SourceLocation(path=name + (".py" if python else ".js"), line=1),
    )


def test_diagnostic_denominators_separate_server_external_resource_builtin(tmp_path):
    available = _node("server", "server", python=True)
    remote = _node("remote", "remote", python=True)
    local = _node("local", "local", python=True)
    template = _node("template", "template", python=True)
    filesystem = _node("file", "file", python=True)
    intrinsic = _node("builtin", "builtin", python=True)

    add_contract(available, "http_server", "/health", 0.98, methods=["GET"])
    add_contract(remote, "http_client", "https://remote.example/api", 0.98)
    add_contract(local, "http_client", "/not-proven", 0.98)
    add_contract(template, "template_render", "missing_template.html", 0.98)
    add_contract(template, "template_tag_library", "static", 0.98)
    add_contract(filesystem, "file_write", "output.csv", 0.98)
    intrinsic.attributes.setdefault("python", {})["unresolved_calls"] = [
        "len", "isinstance", "self.dynamic_call",
    ]
    graph = SemanticGraph(nodes=[
        available, remote, local, template, filesystem, intrinsic,
    ])
    graph.metadata["django_drf"] = {
        "unresolved": [{"reason": "permission_classes:dynamic_expression"}],
    }
    IntegrationResolver().resolve(graph)
    diagnostics = graph.metadata["integration"]
    assert diagnostics["unresolved_contracts"] == 6
    classified = diagnostics["diagnostics_v2"]
    assert classified["raw_unmatched_contract_count"] == 6
    assert classified["classified_unmatched_contract_count"] == 6
    assert classified["actionable_review_candidate_count"] == 2
    assert classified["non_actionable_or_unproven_count"] == 4
    assert classified["counts_by_category"] == {
        "available_boundary_without_local_consumer": 1,
        "external_address_not_proven_local": 1,
        "framework_intrinsic": 1,
        "local_static_target_requires_review": 2,
        "resource_io_without_local_peer": 1,
    }
    assert classified["python_intrinsic_unresolved_calls"] == 2
    assert classified["python_other_unresolved_calls"] == 1
    assert classified["framework_unresolved_observations"]["django_drf"] == 1
    assert all(
        item["evidence_status"] == "unmatched_contract_not_proven_failure"
        for item in classified["classified_sample"]
        if item["actionable_review_candidate"]
    )


def test_resolved_client_server_not_miscounted_as_unmatched_and_exported_is_normal():
    request = _node("request", "request", python=True)
    handler = _node("handler", "handler", python=True)
    other = _node("other", "other", python=True)
    add_contract(request, "http_client", "/books", 0.98, method="GET")
    add_contract(handler, "http_server", "/books", 0.98, methods=["GET"])
    add_contract(other, "http_server", "/status", 0.98, methods=["GET"])
    graph = SemanticGraph(nodes=[request, handler, other])
    IntegrationResolver().resolve(graph)
    d = graph.metadata["integration"]["diagnostics_v2"]
    assert d["raw_unmatched_contract_count"] == 1
    assert d["counts_by_category"] == {
        "available_boundary_without_local_consumer": 1,
    }
    assert d["actionable_review_candidate_count"] == 0
