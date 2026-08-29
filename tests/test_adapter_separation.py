from feynmap import EdgeKind, FeynMapEngine, NodeKind


def _node(graph, name):
    matches = [node for node in graph.nodes if node.name == name]
    assert matches, "missing node %s" % name
    return matches[0]


def test_python_adapter_is_framework_neutral(tmp_path):
    (tmp_path / "requirements.txt").write_text("Django>=5\n", encoding="utf-8")
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "models.py").write_text(
        "from django.db import models\n"
        "class User(models.Model):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "views.py").write_text(
        "from .models import User\n"
        "def helper():\n"
        "    return 1\n"
        "def user_view(request):\n"
        "    helper()\n"
        "    return User()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), framework="none")
    user = _node(graph, "User")
    view = _node(graph, "user_view")

    assert user.kind == NodeKind.CLASS
    assert view.kind == NodeKind.FUNCTION
    assert user.framework is None
    assert view.framework is None
    assert graph.metadata["adapter"] == "python-ast"
    assert graph.metadata["source_model"] == "framework-neutral-python"

    call_targets = {
        edge.target
        for edge in graph.edges
        if edge.source == view.id and edge.kind == EdgeKind.CALLS
    }
    assert _node(graph, "helper").id in call_targets
    assert user.id in call_targets


def test_django_adapter_enriches_generic_python_graph(tmp_path):
    (tmp_path / "requirements.txt").write_text("Django>=5\n", encoding="utf-8")
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "models.py").write_text(
        "from django.db import models\n"
        "class User(models.Model):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "views.py").write_text(
        "def dashboard(request):\n"
        "    return None\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), framework="auto")

    assert graph.metadata["framework"] == "django"
    assert graph.metadata["framework_adapter"] == "django"
    assert _node(graph, "User").kind == NodeKind.DATA_MODEL
    assert _node(graph, "dashboard").kind == NodeKind.HANDLER
    assert any(item.kind.value == "framework_analysis" for item in _node(graph, "User").evidence)


def test_flask_and_fastapi_are_independent_framework_adapters(tmp_path):
    flask_root = tmp_path / "flask_app"
    flask_root.mkdir()
    (flask_root / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (flask_root / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def home():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    flask_graph = FeynMapEngine().analyze(str(flask_root))
    assert flask_graph.metadata["framework"] == "flask"
    assert _node(flask_graph, "home").kind == NodeKind.HANDLER

    fastapi_root = tmp_path / "fastapi_app"
    fastapi_root.mkdir()
    (fastapi_root / "requirements.txt").write_text("fastapi\npydantic\n", encoding="utf-8")
    (fastapi_root / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "from pydantic import BaseModel\n"
        "app = FastAPI()\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "@app.get('/items')\n"
        "async def items():\n"
        "    return []\n",
        encoding="utf-8",
    )
    fastapi_graph = FeynMapEngine().analyze(str(fastapi_root))
    assert fastapi_graph.metadata["framework"] == "fastapi"
    assert _node(fastapi_graph, "items").kind == NodeKind.HANDLER
    assert _node(fastapi_graph, "Item").kind == NodeKind.TRANSFORMER
