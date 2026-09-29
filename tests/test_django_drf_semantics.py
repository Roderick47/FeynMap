"""P1.6: static DRF identity, relationship, coverage and negative fixtures."""
from pathlib import Path

from feynmap.core import ConfidenceTier, EdgeKind, EvidenceKind, NodeKind, SemanticGraph
from feynmap.engine import FeynMapEngine


def _write(root: Path, files):
    for relative, source in files.items():
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8")


def _analyze(root):
    return FeynMapEngine().analyze(str(root), language="auto", framework="django")


def _one(graph, name):
    matches = [node for node in graph.nodes if node.qualified_name == name]
    assert len(matches) == 1, (name, [node.qualified_name for node in matches])
    return matches[0]


def _edges(graph, node, relationship):
    return [
        (edge, graph.node(edge.target))
        for edge in graph.outgoing(node.id)
        if edge.attributes.get("framework", {}).get("relationship")
        == "drf_" + relationship
    ]


def _core():
    return {
        "rest_framework/__init__.py": "",
        "rest_framework/serializers.py": (
            "from rest_framework.fields import Field\n"
            "class BaseSerializer(Field): pass\n"
            "class SerializerMetaclass(type):\n"
            "    @classmethod\n"
            "    def _get_declared_fields(cls, bases, attrs):\n"
            "        return {name: value for name, value in attrs.items()\n"
            "                if isinstance(value, Field)}\n"
            "class Serializer(BaseSerializer, metaclass=SerializerMetaclass): pass\n"
            "class ModelSerializer(Serializer): pass\n"
        ),
        "rest_framework/fields.py": (
            "class Field: pass\n"
            "class CharField(Field): pass\n"
        ),
        "rest_framework/views.py": "class APIView: pass\n",
        "rest_framework/permissions.py": (
            "class BasePermission: pass\n"
            "class IsAuthenticated(BasePermission): pass\n"
        ),
    }


def _app():
    files = _core()
    files.update({
        "catalog/__init__.py": "",
        "catalog/models.py": (
            "from django.db import models\n"
            "class Book(models.Model): pass\n"
        ),
        "app/__init__.py": "",
        "app/serializers.py": (
            "from rest_framework import serializers as drf_ser\n"
            "from catalog.models import Book as ModelBook\n"
            "class BookSerializer(drf_ser.ModelSerializer):\n"
            "    title = drf_ser.CharField(max_length=128)\n"
            "    class Meta:\n"
            "        model = ModelBook\n"
            "        fields = ('id', 'title')\n"
            "    def validate_title(self, value): return value\n"
        ),
        "app/views.py": (
            "from rest_framework.views import APIView as View\n"
            "from rest_framework.permissions import IsAuthenticated as Auth\n"
            "from app.serializers import BookSerializer as Book\n"
            "class BookView(View):\n"
            "    serializer_class = Book\n"
            "    permission_classes = [Auth]\n"
        ),
        "app/urls.py": (
            "from django.urls import path\n"
            "from app.views import BookView\n"
            "urlpatterns = [path('books/', BookView.as_view(), name='books')]\n"
        ),
    })
    return files


def test_explicit_view_serializer_model_permission_and_static_route(tmp_path):
    _write(tmp_path, _app())
    graph = _analyze(tmp_path)
    view = _one(graph, "app.views.BookView")
    serializer = _one(graph, "app.serializers.BookSerializer")
    model = _one(graph, "catalog.models.Book")
    permission = _one(graph, "rest_framework.permissions.IsAuthenticated")
    assert view.kind == NodeKind.HANDLER
    assert serializer.kind == NodeKind.TRANSFORMER
    assert [(edge.kind, node.id) for edge, node in _edges(
        graph, view, "view_serializer"
    )] == [(EdgeKind.SERIALIZES, serializer.id)]
    assert [(edge.kind, node.id) for edge, node in _edges(
        graph, serializer, "serializer_model"
    )] == [(EdgeKind.SERIALIZES, model.id)]
    permission_edges = _edges(graph, view, "view_permission")
    assert [(edge.kind, node.id) for edge, node in permission_edges] == [
        (EdgeKind.DEPENDS_ON, permission.id),
    ]
    for edge, _ in (
        _edges(graph, view, "view_serializer")
        + _edges(graph, serializer, "serializer_model")
        + permission_edges
    ):
        assert edge.confidence_tier == ConfidenceTier.SUPPORTED
        assert edge.evidence[0].kind == EvidenceKind.STATIC
        assert edge.evidence[0].location.path in {
            "app/views.py", "app/serializers.py",
        }
    detail = serializer.attributes["drf_serializer"]
    assert detail["meta"]["fields"] == ["id", "title"]
    assert detail["meta"]["model_declaration"] == "catalog.models.Book"
    assert detail["meta"]["resolved_model_node_id"] == model.id
    assert detail["declared_fields"][0]["name"] == "title"
    assert detail["validation_methods"] == ["validate_title"]
    coverage = [item for item in graph.metadata["django_drf"]["route_coverage"]
                if item["view_node_id"] == view.id]
    assert len(coverage) == 1
    assert coverage[0]["status"] == "static_url_registration"
    assert coverage[0]["static_routes"][0]["path"] == "/books/"
    assert coverage[0]["static_routes"][0]["registration_file"] == "app/urls.py"
    restored = SemanticGraph.from_dict(graph.to_dict())
    assert restored.metadata["django_drf"] == graph.metadata["django_drf"]


def test_literal_core_serializer_metaclass_field_usage_is_source_evidenced(tmp_path):
    _write(tmp_path, _core())
    graph = _analyze(tmp_path)
    method = _one(
        graph,
        "rest_framework.serializers.SerializerMetaclass._get_declared_fields",
    )
    field = _one(graph, "rest_framework.fields.Field")
    edge_matches = [
        edge for edge in graph.outgoing(method.id)
        if edge.target == field.id and edge.kind == EdgeKind.USES_DATA
        and edge.attributes.get("framework", {}).get("relationship")
        == "drf_declared_field_type_check"
    ]
    assert len(edge_matches) == 1
    assert edge_matches[0].evidence[0].detector == (
        "django.drf.serializer_metaclass_field_type_check"
    )
    assert edge_matches[0].evidence[0].location.path == (
        "rest_framework/serializers.py"
    )
    assert graph.metadata["django_drf"]["stats"][
        "source_grounded_core_field_usage_edges"
    ] == 1


def test_metaclass_named_like_drf_without_exact_core_identity_adds_no_bridge(tmp_path):
    files = _core()
    files["rest_framework/serializers.py"] = (
        "from rest_framework.fields import Field\n"
        "class BaseSerializer(Field): pass\n"
        "class SerializerMetaclass(type):\n"
        "    def _get_declared_fields(self, bases, attrs):\n"
        "        return attrs\n"
        "class Serializer(BaseSerializer, metaclass=SerializerMetaclass): pass\n"
    )
    files["unrelated.py"] = (
        "class SerializerMetaclass(type):\n"
        "    def _get_declared_fields(self, bases, attrs):\n"
        "        return isinstance(attrs, str)\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    assert not any(
        edge.attributes.get("framework", {}).get("relationship")
        == "drf_declared_field_type_check"
        for edge in graph.edges
    )
    assert any(item["reason"]
               == "serializer_metaclass_field_check_not_statically_found"
               for item in graph.metadata["django_drf"]["unresolved"])


def test_dynamic_and_same_named_foreign_classes_do_not_produce_fake_bindings(tmp_path):
    files = _app()
    files["other.py"] = (
        "class Serializer: pass\n"
        "class BookSerializer(Serializer):\n"
        "    class Meta:\n"
        "        fields = list_of_fields\n"
    )
    files["app/views.py"] += (
        "\nclass UncertainView(View):\n"
        "    serializer_class = choose_serializer()\n"
        "    permission_classes = permission_factory()\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    assert _one(graph, "other.BookSerializer").kind == NodeKind.CLASS
    uncertain = _one(graph, "app.views.UncertainView")
    assert not _edges(graph, uncertain, "view_serializer")
    assert not _edges(graph, uncertain, "view_permission")
    assert sorted(uncertain.attributes["drf_view"]["unresolved"]) == [
        "permission_classes:dynamic_expression",
        "serializer_class:unknown_or_dynamic",
    ]


def test_dynamic_model_binding_never_selects_a_same_named_model(tmp_path):
    files = _app()
    files["app/serializers.py"] = (
        "from rest_framework.serializers import ModelSerializer\n"
        "from catalog.models import Book\n"
        "class DynamicSerializer(ModelSerializer):\n"
        "    class Meta:\n"
        "        model = model_for_request()\n"
        "        fields = ['title']\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    serializer = _one(graph, "app.serializers.DynamicSerializer")
    assert not _edges(graph, serializer, "serializer_model")
    assert "meta.model:unknown_or_non_model_serializer" in (
        serializer.attributes["drf_serializer"]["unresolved"]
    )


def test_router_declaration_is_not_fabricated_exposed_url(tmp_path):
    files = _app()
    del files["app/urls.py"]
    files["app/router.py"] = (
        "from rest_framework.routers import DefaultRouter as Router\n"
        "from app.views import BookView\n"
        "router = Router()\n"
        "router.register('catalog', BookView, basename='catalog')\n"
        "urlpatterns = router.urls\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    view = _one(graph, "app.views.BookView")
    coverage = [item for item in graph.metadata["django_drf"]["route_coverage"]
                if item["view_node_id"] == view.id]
    assert len(coverage) == 1
    assert coverage[0]["status"] == "router_declaration_mount_unproven"
    assert coverage[0]["static_routes"] == []
    assert coverage[0]["router_declarations"][0]["declared_prefix"] == "catalog"
    assert coverage[0]["router_declarations"][0]["declared_basename"] == "catalog"
    assert not any(item.get("derivation") == "drf.router.static_route"
                   for item in view.attributes.get("integration_contracts", []))


def test_unproven_route_does_not_mean_unrouted_at_runtime(tmp_path):
    files = _app()
    del files["app/urls.py"]
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    view = _one(graph, "app.views.BookView")
    coverage = [item for item in graph.metadata["django_drf"]["route_coverage"]
                if item["view_node_id"] == view.id]
    assert coverage[0]["status"] == "no_static_registration_proven"
    assert coverage[0]["static_routes"] == []
    assert "not proof" in coverage[0]["note"]


def test_import_alias_resolves_only_exact_serializer_class(tmp_path):
    files = _app()
    files["app/views.py"] = (
        "from rest_framework.views import APIView\n"
        "from app.serializers import BookSerializer as Chosen\n"
        "from other import BookSerializer as Decoy\n"
        "class ViewWithAlias(APIView):\n"
        "    serializer_class = Chosen\n"
    )
    files["other.py"] = "class BookSerializer: pass\n"
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    view = _one(graph, "app.views.ViewWithAlias")
    targets = [node.qualified_name for _, node in
               _edges(graph, view, "view_serializer")]
    assert targets == ["app.serializers.BookSerializer"]



def test_custom_permission_subclass_has_exact_imported_policy_identity(tmp_path):
    files = _app()
    files["app/policies.py"] = (
        "from rest_framework.permissions import BasePermission as Policy\n"
        "class IsOwner(Policy): pass\n"
    )
    files["app/views.py"] += (
        "\nfrom app.policies import IsOwner as Ownership\n"
        "class OwnerOnlyView(View):\n"
        "    permission_classes = [Ownership]\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    view = _one(graph, "app.views.OwnerOnlyView")
    permission = _one(graph, "app.policies.IsOwner")
    assert permission.attributes["drf_permission"]["derivation"] == (
        "source_proven_permission_inheritance"
    )
    assert [(edge.kind, node.id) for edge, node in _edges(
        graph, view, "view_permission"
    )] == [(EdgeKind.DEPENDS_ON, permission.id)]


def test_router_call_inside_other_nested_scope_does_not_bind_global_router(tmp_path):
    files = _app()
    del files["app/urls.py"]
    files["app/router.py"] = (
        "from rest_framework.routers import DefaultRouter\n"
        "from app.views import BookView\n"
        "router = DefaultRouter()\n"
        "def maybe_register():\n"
        "    router.register('not-executed', BookView, basename='unproven')\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    view = _one(graph, "app.views.BookView")
    assert not graph.metadata["django_drf"]["router_declarations"]
    assert next(
        item for item in graph.metadata["django_drf"]["route_coverage"]
        if item["view_node_id"] == view.id
    )["status"] == "no_static_registration_proven"
