"""P1.4 source-authored fixtures; Django is never installed or executed."""
from pathlib import Path

from feynmap.core import ConfidenceTier, EdgeKind, SemanticGraph
from feynmap.engine import FeynMapEngine
from feynmap.integration import contracts
from feynmap.p1_external_baseline import _source_probes


def _write(root: Path, files) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _node(graph, name):
    matches = [node for node in graph.nodes if node.qualified_name == name]
    assert len(matches) == 1, (name, [item.qualified_name for item in matches])
    return matches[0]


def _routes(graph, source):
    return [
        (edge, graph.node(edge.target))
        for edge in graph.outgoing(source.id) if edge.kind == EdgeKind.ROUTES_TO
        and edge.attributes.get("integration", {}).get("source_contract", {}).get(
            "kind") == "django_url_reverse"
    ]


def _fixture():
    return {
        "project/urls.py": (
            "from django.urls import path, include\n"
            "urlpatterns = [path('catalog/', include('catalog.urls'))]\n"
        ),
        "catalog/urls.py": (
            "from django.urls import path as route\n"
            "from . import views as screens\n"
            "app_name = 'catalog'\n"
            "urlpatterns = [\n"
            "    route('books/', screens.BookListView.as_view(), name='books'),\n"
            "    route('book/<int:pk>/', screens.BookDetailView.as_view(), name='book-detail'),\n"
            "]\n"
        ),
        "catalog/views.py": (
            "from django.views import generic\n"
            "from django.urls import reverse as django_reverse, reverse_lazy\n"
            "from .models import Book\n"
            "class BookListView(generic.ListView):\n"
            "    model = Book\n"
            "class BookDetailView(generic.DetailView):\n"
            "    model = Book\n"
            "def show_books(request):\n"
            "    return django_reverse('catalog:books')\n"
            "def lazy_detail(request):\n"
            "    return reverse_lazy(viewname='catalog:book-detail')\n"
            "def missing(request):\n"
            "    return django_reverse('catalog:missing')\n"
            "def dynamic(request, viewname):\n"
            "    return django_reverse(viewname)\n"
            "def bare_name(request):\n"
            "    return django_reverse('books')\n"
        ),
        "catalog/models.py": (
            "from django.db import models\n"
            "class Book(models.Model):\n"
            "    title = models.CharField(max_length=100)\n"
        ),
        "catalog/templates/catalog/books.html": (
            "<a href=\"{% url 'catalog:books' %}\">Books</a>\n"
            "{% url 'catalog:book-detail' book.pk %}\n"
            "{% url dynamic_name %}\n"
            "{% url 'catalog:missing' %}\n"
            "{% url 'books' %}\n"
            "{% comment %}{% url 'catalog:books' %}{% endcomment %}\n"
            "<!-- {% url 'catalog:books' %} -->\n"
            "{% verbatim %}{% url 'catalog:books' %}{% endverbatim %}\n"
        ),
    }


def test_namespaced_registration_and_python_template_reversals(tmp_path):
    _write(tmp_path, _fixture())
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    listing = _node(graph, "catalog.views.BookListView")
    detail = _node(graph, "catalog.views.BookDetailView")
    server = contracts(listing, "http_server")
    named = [item for item in server if item.get("name") == "books"]
    assert len(named) == 1, server
    assert named[0]["target"] == "/catalog/books/"
    assert named[0]["route_name"] == "catalog:books"
    assert named[0]["source_file"] == "catalog/urls.py"
    assert named[0]["source_line"] == 5
    assert named[0]["evidence_kind"] == "static"
    assert named[0]["derivation"] == "django.urls.static_registration"

    show = _node(graph, "catalog.views.show_books")
    lazy = _node(graph, "catalog.views.lazy_detail")
    assert [(target.id, edge.confidence_tier) for edge, target in _routes(graph, show)] == [
        (listing.id, ConfidenceTier.SUPPORTED)
    ]
    assert [target.id for edge, target in _routes(graph, lazy)] == [detail.id]
    reverse = contracts(show, "django_url_reverse")
    assert len(reverse) == 1 and reverse[0]["api"] == "reverse"
    assert reverse[0]["target"] == "catalog:books"
    assert reverse[0]["source_file"] == "catalog/views.py"
    assert _routes(graph, _node(graph, "catalog.views.missing")) == []
    assert _routes(graph, _node(graph, "catalog.views.dynamic")) == []
    assert contracts(_node(graph, "catalog.views.dynamic"), "django_url_reverse") == []
    assert _routes(graph, _node(graph, "catalog.views.bare_name")) == []

    template = _node(graph, "catalog/templates/catalog/books.html")
    template_refs = contracts(template, "django_url_reverse")
    assert [item["target"] for item in template_refs] == [
        "catalog:books", "catalog:book-detail", "catalog:missing", "books",
    ]
    assert not any(
        item["target"].startswith("{% url")
        for item in contracts(template, "http_client")
    )
    assert {target.id for edge, target in _routes(graph, template)} == {
        listing.id, detail.id,
    }
    assert all(edge.confidence_tier == ConfidenceTier.SUPPORTED
               for edge, target in _routes(graph, template))

    records = graph.metadata["django_named_urls"]
    assert records["version"] == "1.0.0"
    assert any(item["route_name"] == "catalog:books" for item in records["registrations"])
    assert any(row["reason"] == "dynamic_or_invalid_reverse_name"
               for row in records["unresolved"])
    restored = SemanticGraph.from_dict(graph.to_dict())
    assert restored.metadata["django_named_urls"] == records
    assert [target.id for edge, target in _routes(restored, show)] == [listing.id]


def test_independent_mdn_named_route_probe_is_grounded(tmp_path):
    _write(tmp_path, {
        "catalog/urls.py": (
            "from django.urls import path\n"
            "from . import views\n"
            "urlpatterns = [path('books/', views.BookListView.as_view(), name='books')]\n"
        ),
        "catalog/views.py": (
            "from django.views.generic import ListView\n"
            "class BookListView(ListView):\n"
            "    pass\n"
        ),
    })
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    report = _source_probes(graph, {
        "category": "http_route", "source_file": "catalog/urls.py",
        "source_line": 3, "source_symbol": "BookListView",
        "expected_target": "books",
    })
    assert report["passed"] is True
    contract = next(item for item in report["observed_contracts"]
                    if item.get("name") == "books")
    assert contract["route_name"] == "books"
    assert contract["target"] == "/books/"
    assert contract["source_file"] == "catalog/urls.py"


def test_same_named_views_are_not_guessed_and_unrelated_path_is_ignored(tmp_path):
    _write(tmp_path, {
        "catalog/urls.py": (
            "from django.urls import path\n"
            "from .views import BookListView as list_books\n"
            "urlpatterns = [path('books/', list_books.as_view(), name='books')]\n"
        ),
        "catalog/views.py": (
            "from django.views.generic import ListView\n"
            "class BookListView(ListView): pass\n"
        ),
        "other/views.py": (
            "from django.views.generic import ListView\n"
            "class BookListView(ListView): pass\n"
            "def path(*args, **kwargs): pass\n"
            "def unrelated(): return path('bogus/', BookListView.as_view(), name='bogus')\n"
        ),
    })
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    assert len([item for item in contracts(
        _node(graph, "catalog.views.BookListView"), "http_server"
    ) if item.get("name") == "books"]) == 1
    assert not [item for item in contracts(
        _node(graph, "other.views.BookListView"), "http_server"
    ) if item.get("name") in {"books", "bogus"}]


def test_duplicate_full_name_and_wrong_import_stay_unresolved(tmp_path):
    _write(tmp_path, {
        "app/urls.py": (
            "from django.urls import path\n"
            "from . import views\n"
            "urlpatterns = [\n"
            " path('a/', views.First.as_view(), name='same'),\n"
            " path('b/', views.Second.as_view(), name='same'),\n"
            " path('c/', views.Third.as_view(), name=unknown_name),\n"
            "]\n"
        ),
        "app/views.py": (
            "from django.views.generic import ListView\n"
            "from unrelated import reverse\n"
            "from django.urls import reverse_lazy\n"
            "class First(ListView): pass\n"
            "class Second(ListView): pass\n"
            "class Third(ListView): pass\n"
            "def duplicate(): return reverse_lazy('same')\n"
            "def impostor(): return reverse('same')\n"
        ),
        "app/template.html": "{% url 'same' %}",
    })
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    assert _routes(graph, _node(graph, "app.views.duplicate")) == []
    assert _routes(graph, _node(graph, "app/template.html")) == []
    assert contracts(_node(graph, "app.views.impostor"), "django_url_reverse") == []
    assert any(item["reason"] == "dynamic_name"
               for item in graph.metadata["django_named_urls"]["unresolved"])
    third = _node(graph, "app.views.Third")
    assert not any(item.get("name") for item in contracts(third, "http_server"))


def test_explicit_include_namespace_disambiguates_reused_leaf_names(tmp_path):
    _write(tmp_path, {
        "project/urls.py": (
            "from django.urls import include, path\n"
            "urlpatterns = [\n"
            " path('first/', include(('one.urls', 'catalog'), namespace='first')),\n"
            " path('second/', include(('two.urls', 'catalog'), namespace='second')),\n"
            "]\n"
        ),
        "one/urls.py": (
            "from django.urls import path\n"
            "from . import views\n"
            "urlpatterns = [path('books/', views.ListView.as_view(), name='books')]\n"
        ),
        "two/urls.py": (
            "from django.urls import path\n"
            "from . import views\n"
            "urlpatterns = [path('books/', views.ListView.as_view(), name='books')]\n"
        ),
        "one/views.py": (
            "from django.views.generic import ListView as BaseListView\n"
            "class ListView(BaseListView): pass\n"
            "from django.urls import reverse\n"
            "def first(request): return reverse('first:books')\n"
        ),
        "two/views.py": (
            "from django.views.generic import ListView as BaseListView\n"
            "class ListView(BaseListView): pass\n"
            "from django.urls import reverse\n"
            "def second(request): return reverse('second:books')\n"
        ),
    })
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    one = _node(graph, "one.views.ListView")
    two = _node(graph, "two.views.ListView")
    assert [target.id for edge, target in _routes(
        graph, _node(graph, "one.views.first"))] == [one.id]
    assert [target.id for edge, target in _routes(
        graph, _node(graph, "two.views.second"))] == [two.id]
    assert [item["target"] for item in contracts(one, "http_server")
            if item.get("name") == "books"] == ["/first/books/"]
    assert [item["route_name"] for item in contracts(two, "http_server")
            if item.get("name") == "books"] == ["second:books"]
