"""P1.1b baseline scoring tests; oracle facts must not be auto-rewritten."""
from pathlib import Path

import pytest

from feynmap.core import (
    EdgeKind, Evidence, EvidenceKind, NodeKind,
    SemanticEdge, SemanticGraph, SemanticNode, SourceLocation,
)
from feynmap.integration import add_contract
from feynmap.p1_external_baseline import (
    _file_channel, _source_probes, evaluate_fixture,
)


def _node(identifier, name, path, kind=NodeKind.CLASS):
    return SemanticNode(
        id=identifier,
        name=name,
        kind=kind,
        language="python" if kind != NodeKind.UI_SURFACE else "html",
        location=SourceLocation(path=path, line=1),
    )


def test_explicit_django_model_requires_a_real_model_edge_not_file_cooccurrence():
    book_view = _node("view", "BookListView", "catalog/views.py", NodeKind.HANDLER)
    book_model = _node("book", "Book", "catalog/models.py", NodeKind.DATA_MODEL)
    graph = SemanticGraph(nodes=[book_view, book_model])
    probe = {
        "category": "framework_relationship",
        "source_file": "catalog/views.py", "source_symbol": "BookListView",
        "target_file": "catalog/models.py", "target_symbol": "Book",
        "relationship": "uses_model",
    }
    initial = _source_probes(graph, probe)
    assert initial["status"] == "missing_relationship"
    assert initial["source_node_count"] == 1
    assert initial["passed"] is False

    graph.add_edge(SemanticEdge(
        id="real-uses-data", source="view", target="book",
        kind=EdgeKind.USES_DATA, confidence=0.98,
        evidence=[Evidence(
            EvidenceKind.STATIC, "fixture.model_assignment",
            "model = Book", book_view.location, 0.98,
        )],
    ))
    after = _source_probes(graph, probe)
    assert after["status"] == "matched_relationship"
    assert after["passed"] is True
    assert after["matching_edges"][0]["target_id"] == "book"


def test_explicit_template_contract_without_edge_is_not_counted_as_coverage():
    owner = _node("view", "BookListView", "catalog/views.py", NodeKind.HANDLER)
    template = _node(
        "template", "book_list.html",
        "catalog/templates/catalog/book_list.html", NodeKind.UI_SURFACE,
    )
    add_contract(owner, "template_render", "catalog/book_list.html", 0.96)
    graph = SemanticGraph(nodes=[owner, template])
    probe = {
        "category": "framework_inference",
        "source_file": "catalog/views.py", "source_symbol": "BookListView",
        "target_file": "catalog/templates/catalog/book_list.html",
        "relationship": "renders_template",
    }
    result = _source_probes(graph, probe)
    assert result["status"] == "contract_without_resolved_edge"
    assert result["passed"] is False


def test_flask_blueprint_probe_detects_raw_route_prefix_gap():
    token = _node("token", "get_token", "app/api/tokens.py", NodeKind.HANDLER)
    add_contract(token, "http_server", "/tokens", 0.99, methods=["POST"])
    graph = SemanticGraph(nodes=[token])
    probe = {
        "category": "http_route", "source_file": "app/api/tokens.py",
        "source_symbol": "get_token", "expected_path": "/api/tokens",
        "expected_method": "POST",
    }
    result = _source_probes(graph, probe)
    assert result["status"] == "path_or_method_mismatch"
    assert result["passed"] is False
    assert result["observed_contracts"][0]["target"] == "/tokens"
    add_contract(token, "http_server", "/api/tokens", 0.99, methods=["POST"])
    corrected = _source_probes(graph, probe)
    assert corrected["passed"] is True


def test_named_route_rejects_unnamed_http_server_contract():
    view = _node("view", "BookListView", "catalog/views.py", NodeKind.HANDLER)
    add_contract(view, "http_server", "/books/", 0.93, methods=["ANY"])
    graph = SemanticGraph(nodes=[view])
    probe = {
        "category": "http_route", "source_file": "catalog/urls.py",
        "source_symbol": "BookListView", "expected_target": "books",
    }
    # Source location must be the view's file, not the URL registration file.
    probe["source_file"] = "catalog/views.py"
    result = _source_probes(graph, probe)
    assert result["status"] == "route_present_but_name_missing"
    assert result["passed"] is False


def test_file_roles_count_migrations_and_tests_separately():
    assert _file_channel("tests/test_api.py") == "test"
    assert _file_channel("rest_framework/tests/test_throttling.py") == "test"
    assert _file_channel("catalog/migrations/0001_initial.py") == "migration"
    assert _file_channel("static/vendor/jquery.min.js") == "vendor_or_generated"
    assert _file_channel("rest_framework/throttling.py") == "implementation_or_other"


def test_baseline_rejects_wrong_revision_before_analyzing(monkeypatch, tmp_path: Path):
    class DoNotRun:
        def analyze(self, *args, **kwargs):
            pytest.fail("analysis was run on an unpinned checkout")

    monkeypatch.setattr(
        "feynmap.p1_external_baseline.FeynMapEngine",
        lambda: DoNotRun(),
    )
    with pytest.raises(ValueError, match="pinned checkout mismatch"):
        evaluate_fixture(
            {"id": "fixed", "commit": "a" * 40, "framework": "django", "probes": []},
            tmp_path,
            actual_commit="b" * 40,
        )
