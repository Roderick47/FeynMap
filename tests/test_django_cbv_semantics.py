"""P1.2: source-authored Django CBV model/template regression fixtures.

These fixtures deliberately include ambiguous/dynamic cases: a graph must
preserve UNKNOWN rather than connect a same-named but unsupported model.
No Django code is imported, installed or executed.
"""
from pathlib import Path

from feynmap.core import ConfidenceTier, EdgeKind, EvidenceKind, NodeKind
from feynmap.engine import FeynMapEngine
from feynmap.integration import contracts


MODEL = """from django.db import models
class Book(models.Model):
    title = models.CharField(max_length=10)
class Author(models.Model):
    name = models.CharField(max_length=10)
"""


def _write(root: Path, mapping) -> None:
    for path, content in mapping.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _graph(root: Path):
    return FeynMapEngine().analyze(str(root), language="auto", framework="django")


def _symbol(graph, qualified: str):
    matches = [
        node for node in graph.nodes
        if node.qualified_name == qualified and node.language == "python"
    ]
    assert len(matches) == 1, (qualified, [node.qualified_name for node in matches])
    return matches[0]


def _render_edges(graph, source):
    return [
        (edge, graph.node(edge.target))
        for edge in graph.outgoing(source.id)
        if edge.kind == EdgeKind.RENDERS
    ]


def _model_edges(graph, source):
    return [
        (edge, graph.node(edge.target))
        for edge in graph.outgoing(source.id)
        if edge.kind == EdgeKind.USES_DATA
        and edge.attributes.get("framework", {}).get("relationship") == "cbv_uses_model"
    ]


def _base_fixture():
    return {
        "catalog/models.py": MODEL,
        "catalog/__init__.py": "",
        "catalog/views.py": (
            "from django.views import generic\n"
            "from .models import Book, Author\n"
            "class BookListView(generic.ListView):\n"
            "    model = Book\n"
            "class BookDetailView(generic.DetailView):\n"
            "    model: type = Book\n"
            "class AuthorByUser(generic.ListView):\n"
            "    model = Author\n"
            "    template_name = 'catalog/author_custom.html'\n"
        ),
        "catalog/templates/catalog/book_list.html": "<p>Book list</p>",
        "catalog/templates/catalog/book_detail.html": "<p>Book detail</p>",
        "catalog/templates/catalog/author_custom.html": "<p>Author custom</p>",
    }


def test_source_model_edges_and_default_template_are_not_mistaken_for_verified(tmp_path):
    _write(tmp_path, _base_fixture())
    graph = _graph(tmp_path)
    book = _symbol(graph, "catalog.models.Book")
    view = _symbol(graph, "catalog.views.BookListView")
    edges = _model_edges(graph, view)
    assert len(edges) == 1
    edge, target = edges[0]
    assert target.id == book.id
    assert edge.confidence_tier == ConfidenceTier.SUPPORTED
    assert edge.evidence[0].kind == EvidenceKind.STATIC
    assert edge.evidence[0].detector == "django.cbv.model_assignment"
    assert edge.evidence[0].location.path == "catalog/views.py"
    assert edge.attributes["django_cbv"]["resolved_model"] == "catalog.models.Book"

    default = _render_edges(graph, view)
    assert len(default) == 1
    render, html = default[0]
    assert html.location.path == "catalog/templates/catalog/book_list.html"
    assert render.confidence_tier == ConfidenceTier.INFERRED
    assert render.attributes["integration"]["source_contract"]["derivation"] == (
        "django.cbv.default_template"
    )
    assert render.attributes["integration"]["source_contract"]["inferred_from"] == (
        "catalog.models.Book"
    )
    assert view.attributes["django_cbv"]["template_evidence"] == "framework_convention"

    details = _symbol(graph, "catalog.views.BookDetailView")
    assert [(target.id, edge.kind) for edge, target in _model_edges(graph, details)] == [
        (book.id, EdgeKind.USES_DATA)
    ]
    assert [html.location.path for edge, html in _render_edges(graph, details)] == [
        "catalog/templates/catalog/book_detail.html"
    ]


def test_explicit_template_contract_has_source_evidence_and_no_default(tmp_path):
    _write(tmp_path, _base_fixture())
    graph = _graph(tmp_path)
    author = _symbol(graph, "catalog.views.AuthorByUser")
    linked = _render_edges(graph, author)
    assert len(linked) == 1
    edge, template = linked[0]
    assert template.location.path == "catalog/templates/catalog/author_custom.html"
    assert edge.confidence_tier == ConfidenceTier.SUPPORTED
    contract = edge.attributes["integration"]["source_contract"]
    assert contract["derivation"] == "django.cbv.explicit_template"
    assert contract["evidence_kind"] == EvidenceKind.STATIC.value
    assert contract["resolved_template_path"] == template.location.path
    assert not any(item.get("derivation") == "django.cbv.default_template"
                   for item in contracts(author, "template_render"))


def test_import_alias_and_queryset_chain_ground_same_model(tmp_path):
    _write(tmp_path, {
        "catalog/models.py": MODEL,
        "catalog/views.py": (
            "from django.views.generic import ListView as CoreList\n"
            "from . import models as domain\n"
            "class FilteredBookList(CoreList):\n"
            "    queryset = domain.Book.objects.filter(title='abc').order_by('title')\n"
        ),
        "catalog/templates/catalog/book_list.html": "<p>Filtered</p>",
    })
    graph = _graph(tmp_path)
    view = _symbol(graph, "catalog.views.FilteredBookList")
    book = _symbol(graph, "catalog.models.Book")
    links = _model_edges(graph, view)
    assert len(links) == 1 and links[0][1].id == book.id
    assert links[0][0].evidence[0].detector == "django.cbv.queryset_assignment"
    assert len(_render_edges(graph, view)) == 1


def test_explicit_templateview_is_grounded_without_model(tmp_path):
    _write(tmp_path, {
        "catalog/views.py": (
            "from django.views.generic.base import TemplateView\n"
            "class Landing(TemplateView):\n"
            "    template_name = 'catalog/landing.html'\n"
        ),
        "catalog/templates/catalog/landing.html": "<p>Landing</p>",
    })
    graph = _graph(tmp_path)
    view = _symbol(graph, "catalog.views.Landing")
    assert _model_edges(graph, view) == []
    edges = _render_edges(graph, view)
    assert len(edges) == 1
    assert edges[0][1].location.path == "catalog/templates/catalog/landing.html"


def test_ambiguous_imports_cannot_turn_short_name_into_wrong_model_edge(tmp_path):
    _write(tmp_path, {
        "catalog/models.py": MODEL,
        "other/models.py": MODEL,
        "catalog/views.py": (
            "from django.views.generic import ListView\n"
            "from catalog.models import Book\n"
            "from other.models import Book\n"
            "class Ambiguous(ListView):\n"
            "    model = Book\n"
        ),
        "catalog/templates/catalog/book_list.html": "<p>One</p>",
        "other/templates/other/book_list.html": "<p>Two</p>",
    })
    graph = _graph(tmp_path)
    view = _symbol(graph, "catalog.views.Ambiguous")
    assert _model_edges(graph, view) == []
    assert _render_edges(graph, view) == []
    assert any("model:unresolved_or_ambiguous" in item
               for item in view.attributes["django_cbv"]["unresolved"])


def test_unrelated_listview_and_same_named_model_are_not_guessed(tmp_path):
    _write(tmp_path, {
        "catalog/models.py": MODEL,
        "other/models.py": MODEL,
        "catalog/views.py": (
            "from .models import Book\n"
            "from unrelated.module import ListView\n"
            "class LocalView(ListView):\n"
            "    model = Book\n"
            "from other.models import Book as OtherBook\n"
            "from django.views.generic import DetailView\n"
            "class ForeignView(DetailView):\n"
            "    model = OtherBook\n"
        ),
        "catalog/templates/catalog/book_detail.html": "<p>Wrong target</p>",
        "other/templates/other/book_detail.html": "<p>Actual target</p>",
    })
    graph = _graph(tmp_path)
    local = _symbol(graph, "catalog.views.LocalView")
    assert "django_cbv" not in local.attributes
    assert _model_edges(graph, local) == []
    foreign = _symbol(graph, "catalog.views.ForeignView")
    foreign_model = _symbol(graph, "other.models.Book")
    assert [target.id for edge, target in _model_edges(graph, foreign)] == [foreign_model.id]
    assert [target.location.path for edge, target in _render_edges(graph, foreign)] == [
        "other/templates/other/book_detail.html"
    ]


def test_missing_or_ambiguous_template_never_creates_fabricated_render_edge(tmp_path):
    files = _base_fixture()
    files["catalog/templates/catalog/book_list.html"] = "<p>One</p>"
    files["other/templates/catalog/book_list.html"] = "<p>Collision</p>"
    files.pop("catalog/templates/catalog/book_detail.html")
    graph_root = tmp_path / "duplicate"
    _write(graph_root, files)
    graph = _graph(graph_root)
    list_view = _symbol(graph, "catalog.views.BookListView")
    detail_view = _symbol(graph, "catalog.views.BookDetailView")
    assert _model_edges(graph, list_view)
    assert _model_edges(graph, detail_view)
    assert _render_edges(graph, list_view) == []
    assert _render_edges(graph, detail_view) == []
    assert not contracts(list_view, "template_render")
    assert not contracts(detail_view, "template_render")


def test_unknown_dynamic_queryset_blocks_default_template_inference(tmp_path):
    _write(tmp_path, {
        "catalog/models.py": MODEL,
        "catalog/views.py": (
            "from django.views.generic import ListView\n"
            "from .models import Book, Author\n"
            "class DynamicBooks(ListView):\n"
            "    model = Book\n"
            "    queryset = choose_runtime_queryset()\n"
            "class CustomTemplate(ListView):\n"
            "    model = Book\n"
            "    def get_template_names(self):\n"
            "        return [runtime_template()]\n"
            "class Conflicting(ListView):\n"
            "    model = Book\n"
            "    queryset = Author.objects.all()\n"
        ),
        "catalog/templates/catalog/book_list.html": "<p>Maybe</p>",
        "catalog/templates/catalog/author_list.html": "<p>Other</p>",
    })
    graph = _graph(tmp_path)
    dynamic = _symbol(graph, "catalog.views.DynamicBooks")
    custom = _symbol(graph, "catalog.views.CustomTemplate")
    assert _model_edges(graph, dynamic)
    assert _render_edges(graph, dynamic) == []
    assert _render_edges(graph, custom) == []
    assert "template:queryset_model_unknown" in dynamic.attributes["django_cbv"]["unresolved"]
    assert "template:custom_queryset_object_or_template" in custom.attributes["django_cbv"]["unresolved"]
    conflicting = _symbol(graph, "catalog.views.Conflicting")
    assert {target.qualified_name for edge, target in _model_edges(graph, conflicting)} == {
        "catalog.models.Book", "catalog.models.Author"
    }
    assert _render_edges(graph, conflicting) == []
    assert "template:missing_or_conflicting_model" in conflicting.attributes["django_cbv"]["unresolved"]


def test_dynamic_explicit_template_stays_unknown_instead_of_using_default(tmp_path):
    _write(tmp_path, {
        "catalog/models.py": MODEL,
        "catalog/views.py": (
            "from django.views.generic import ListView\n"
            "from .models import Book\n"
            "class Books(ListView):\n"
            "    model = Book\n"
            "    template_name = get_template_name()\n"
        ),
        "catalog/templates/catalog/book_list.html": "<p>Must not guess</p>",
    })
    graph = _graph(tmp_path)
    view = _symbol(graph, "catalog.views.Books")
    assert _model_edges(graph, view)
    assert _render_edges(graph, view) == []
    assert view.attributes["django_cbv"]["declared_template_name"] is None



def test_explicit_template_with_custom_template_selection_does_not_claim_render(tmp_path):
    _write(tmp_path, {
        "catalog/views.py": (
            "from django.views.generic import TemplateView\n"
            "class RuntimeTemplate(TemplateView):\n"
            "    template_name = 'catalog/landing.html'\n"
            "    def get_template_names(self):\n"
            "        return [dynamic_template()]\n"
        ),
        "catalog/templates/catalog/landing.html": "<p>Present but not proven to render</p>",
    })
    graph = _graph(tmp_path)
    view = _symbol(graph, "catalog.views.RuntimeTemplate")
    assert _render_edges(graph, view) == []
    assert not contracts(view, "template_render")
    assert "template_name:custom_get_template_names" in view.attributes["django_cbv"]["unresolved"]
