"""P1.3: AppConfig source membership must not become a dependency hub."""
from pathlib import Path

from feynmap import EdgeKind, FeynMapEngine
from feynmap.adapters.frameworks.django import django_app_memberships
from feynmap.core import SemanticGraph
from feynmap.query import FeynMapQuery
from feynmap.routing import RegionIndex


def _write(root: Path, mapping):
    for name, content in mapping.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _node(graph, name):
    matches = [node for node in graph.nodes if node.name == name]
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def _fixture(root):
    _write(root, {
        "requirements.txt": "django\n",
        "manage.py": "",
        "core/__init__.py": "",
        "core/apps.py": (
            "from django.apps import AppConfig\n"
            "class CoreConfig(AppConfig):\n"
            "    name = 'core'\n"
        ),
        "core/models.py": (
            "from django.db import models\n"
            "class Book(models.Model):\n"
            "    title = models.CharField(max_length=120)\n"
        ),
        "core/views.py": (
            "from django.views.generic import ListView\n"
            "from .models import Book\n"
            "def landing(request):\n"
            "    return None\n"
            "class BookListView(ListView):\n"
            "    model = Book\n"
        ),
        "core/templates/core/book_list.html": "<h1>Books</h1>\n",
        "core/shop/__init__.py": "",
        "core/shop/apps.py": (
            "from django.apps import AppConfig\n"
            "class ShopConfig(AppConfig):\n"
            "    name = 'core.shop'\n"
        ),
        "core/shop/views.py": (
            "def checkout(request):\n"
            "    return None\n"
        ),
        "other/__init__.py": "",
        "other/apps.py": (
            "from django.apps import AppConfig\n"
            "class OtherConfig(AppConfig):\n"
            "    name = 'other'\n"
        ),
        "other/views.py": (
            "def privacy(request):\n"
            "    return None\n"
        ),
        # Force the repository orchestrator to merge more than one language.
        "core/templates/base.html": "<main>Unrelated HTML</main>\n",
    })


def test_memberships_are_inferred_and_nearest_without_creating_behavior_edges(tmp_path):
    _fixture(tmp_path)
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    core = _node(graph, "CoreConfig")
    shop = _node(graph, "ShopConfig")
    other = _node(graph, "OtherConfig")
    expected = {
        _node(graph, "landing").id: (core.id, "core"),
        _node(graph, "BookListView").id: (core.id, "core"),
        _node(graph, "checkout").id: (shop.id, "core/shop"),
        _node(graph, "privacy").id: (other.id, "other"),
    }

    membership = graph.metadata["django_app_membership"]
    assert membership["version"] == "1.0.0"
    assert membership["relationship"] == "source_tree_membership_not_behavioral_dependency"
    assert membership["unresolved"] == []
    assert {
        item["handler_node_id"]: (item["app_config_node_id"], item["app_root"])
        for item in membership["associations"]
    } == expected
    for item in membership["associations"]:
        assert item["confidence_tier"] == "inferred"
        assert item["scope"] == "source_tree_only"
        assert item["evidence"]["kind"] == "framework_analysis"
        assert item["evidence"]["detector"] == "django.app_config.source_tree_membership"

    for handler_id, (config_id, _) in expected.items():
        assert [item["app_config_node_id"] for item in django_app_memberships(
            graph, handler_id
        )] == [config_id]
        assert not any(
            edge.target == config_id and edge.source == handler_id
            and edge.kind == EdgeKind.DEPENDS_ON
            for edge in graph.edges
        )
    assert len(django_app_memberships(graph)) == len(expected)

    # Explicit membership metadata survives a combined-language graph and a
    # canonical snapshot round-trip without introducing graph edges.
    restored = SemanticGraph.from_dict(graph.to_dict())
    assert django_app_memberships(restored) == django_app_memberships(graph)
    assert restored.metadata["django_app_membership"] == membership


def test_impact_keeps_grounded_model_view_links_but_not_app_config_hub(tmp_path):
    _fixture(tmp_path)
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    book = _node(graph, "Book")
    view = _node(graph, "BookListView")
    landing = _node(graph, "landing")
    core = _node(graph, "CoreConfig")
    query = FeynMapQuery(graph)

    view_impact = query.impact(book.id, depth=1)
    assert view.id in {item["id"] for item in view_impact["nodes"]}
    assert any(
        item["source"] == view.id and item["target"] == book.id
        and item["kind"] == "uses_data"
        for item in view_impact["edges"]
    )
    # Changing an AppConfig is not blanket evidence of changing every handler.
    app_impact = query.impact(core.id, depth=1)
    assert landing.id not in {item["id"] for item in app_impact["nodes"]}
    assert view.id not in {item["id"] for item in app_impact["nodes"]}
    assert query.validate_claim(landing.id, core.id, "depends_on")["evidence_found"] is False

    # Routing does not create a direct lexical-locality hop from either handler
    # to the unrelated AppConfig source region merely because of app membership.
    index = RegionIndex(graph, native_routing=False)
    view_region = index.region_for_node(view.id)
    config_region = index.region_for_node(core.id)
    assert view_region != config_region
    assert config_region not in index.adjacency[view_region]


def test_equally_near_appconfigs_stay_unresolved_instead_of_guessing(tmp_path):
    _write(tmp_path, {
        "requirements.txt": "django\n",
        "manage.py": "",
        "core/apps.py": (
            "from django.apps import AppConfig\n"
            "class FirstConfig(AppConfig):\n"
            "    name = 'core'\n"
            "class SecondConfig(AppConfig):\n"
            "    name = 'core'\n"
        ),
        "core/views.py": (
            "def show(request):\n"
            "    return None\n"
        ),
    })
    graph = FeynMapEngine().analyze(str(tmp_path), framework="django")
    handler = _node(graph, "show")
    observation = graph.metadata["django_app_membership"]
    assert django_app_memberships(graph, handler.id) == []
    assert len(observation["unresolved"]) == 1
    entry = observation["unresolved"][0]
    assert entry["reason"] == "ambiguous_nearest_app_config"
    assert entry["handler_node_id"] == handler.id
    assert len(entry["candidate_config_node_ids"]) == 2
    assert not any(
        edge.source == handler.id and edge.attributes.get("framework", {}).get(
            "relationship"
        ) == "app_config"
        for edge in graph.edges
    )
