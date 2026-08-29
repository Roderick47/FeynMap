from feynmap import EdgeKind, FeynMapEngine
from feynmap.core import NodeKind, SemanticGraph, SemanticNode
from feynmap.integration import IntegrationResolver, add_contract


def _node(graph, name, language=None):
    matches = [node for node in graph.nodes if node.name == name and (language is None or node.language == language)]
    assert matches, "missing node %s/%s" % (language, name)
    return matches[0]


def _has_edge(graph, source, target, kind):
    return any(edge.source == source.id and edge.target == target.id and edge.kind == kind for edge in graph.edges)


def test_mixed_web_app_becomes_one_cross_language_graph(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "static").mkdir()

    (tmp_path / "app.py").write_text(
        "from flask import Flask, render_template\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/')\n"
        "def home():\n"
        "    return render_template('index.html')\n\n"
        "@app.route('/api/items')\n"
        "def items():\n"
        "    return []\n",
        encoding="utf-8",
    )
    (tmp_path / "templates" / "index.html").write_text(
        "<html><body>\n"
        "<button onclick=\"loadItems()\">Load</button>\n"
        "<script src=\"/static/app.js\"></script>\n"
        "</body></html>\n",
        encoding="utf-8",
    )
    (tmp_path / "static" / "app.js").write_text(
        "function loadItems() {\n"
        "  return fetch('/api/items');\n"
        "}\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path))

    assert {"python", "html", "javascript"}.issubset(set(graph.metadata["language_names"]))
    assert graph.metadata["language_count"] >= 3

    home = _node(graph, "home", "python")
    items = _node(graph, "items", "python")
    html = _node(graph, "index.html", "html")
    js_module = _node(graph, "app.js", "javascript")
    load_items = _node(graph, "loadItems", "javascript")

    assert _has_edge(graph, home, html, EdgeKind.RENDERS)
    assert _has_edge(graph, html, js_module, EdgeKind.LOADS)
    assert _has_edge(graph, html, load_items, EdgeKind.INVOKES)
    assert _has_edge(graph, load_items, items, EdgeKind.REQUESTS)
    assert graph.metadata["integration"]["resolved_edges"] >= 4


def test_fastapi_route_is_resolved_from_javascript_client(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.get('/health')\n"
        "async def health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (tmp_path / "client.js").write_text(
        "async function checkHealth() { return fetch('/health'); }\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path))
    check = _node(graph, "checkHealth", "javascript")
    health = _node(graph, "health", "python")

    assert graph.metadata["framework"] == "fastapi"
    assert _has_edge(graph, check, health, EdgeKind.REQUESTS)


def test_django_urlpattern_is_resolved_from_javascript_client(tmp_path):
    (tmp_path / "requirements.txt").write_text("django\n", encoding="utf-8")
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "views.py").write_text(
        "def dashboard(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (tmp_path / "urls.py").write_text(
        "from django.urls import path\n"
        "from views import dashboard\n"
        "urlpatterns = [path('dashboard/', dashboard)]\n",
        encoding="utf-8",
    )
    (tmp_path / "client.js").write_text(
        "function openDashboard() { return fetch('/dashboard/'); }\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path))
    client = _node(graph, "openDashboard", "javascript")
    dashboard = _node(graph, "dashboard", "python")

    assert graph.metadata["framework"] == "django"
    assert _has_edge(graph, client, dashboard, EdgeKind.REQUESTS)


def test_resolver_supports_dynamic_http_route_parameters():
    client = SemanticNode("client", "client", NodeKind.FUNCTION, language="javascript")
    server = SemanticNode("server", "server", NodeKind.HANDLER, language="python")
    add_contract(client, "http_client", "/users/42", method="GET")
    add_contract(server, "http_server", "/users/<int:user_id>", methods=["GET"])
    graph = SemanticGraph(nodes=[client, server])

    IntegrationResolver().resolve(graph)

    assert _has_edge(graph, client, server, EdgeKind.REQUESTS)


def test_resolver_supports_non_web_cross_language_channels():
    producer = SemanticNode("js", "desktop", NodeKind.FUNCTION, language="javascript")
    worker = SemanticNode("py", "worker", NodeKind.MODULE, language="python")
    publisher = SemanticNode("rust", "publisher", NodeKind.FUNCTION, language="rust")
    subscriber = SemanticNode("java", "subscriber", NodeKind.METHOD, language="java")
    ffi_user = SemanticNode("swift", "nativeCall", NodeKind.FUNCTION, language="swift")
    ffi_export = SemanticNode("cpp", "native_call", NodeKind.FUNCTION, language="cpp")
    writer = SemanticNode("writer", "writer", NodeKind.FUNCTION, language="python")
    reader = SemanticNode("reader", "reader", NodeKind.FUNCTION, language="javascript")
    deep_link = SemanticNode("deeplink", "openApp", NodeKind.FUNCTION, language="javascript")
    app_route = SemanticNode("route", "nativeRoute", NodeKind.HANDLER, language="kotlin")

    add_contract(producer, "process_spawn", "worker.py")
    add_contract(worker, "cli_entrypoint", "worker.py")
    add_contract(publisher, "queue_publish", "orders.created")
    add_contract(subscriber, "queue_subscribe", "orders.created")
    add_contract(ffi_user, "ffi_import", "native_call")
    add_contract(ffi_export, "ffi_export", "native_call")
    add_contract(writer, "file_write", "shared/data.json")
    add_contract(reader, "file_read", "shared/data.json")
    add_contract(deep_link, "deep_link", "myapp://orders/42")
    add_contract(app_route, "app_route", "myapp://orders/42")

    graph = SemanticGraph(nodes=[producer, worker, publisher, subscriber, ffi_user, ffi_export, writer, reader, deep_link, app_route])
    IntegrationResolver().resolve(graph)

    assert _has_edge(graph, producer, worker, EdgeKind.SPAWNS)
    assert _has_edge(graph, publisher, subscriber, EdgeKind.EMITS)
    assert _has_edge(graph, ffi_user, ffi_export, EdgeKind.INVOKES)
    assert _has_edge(graph, writer, reader, EdgeKind.FLOWS_TO)
    assert _has_edge(graph, deep_link, app_route, EdgeKind.ROUTES_TO)
    assert all(edge.attributes.get("integration", {}).get("cross_language") for edge in graph.edges)


def test_javascript_can_spawn_python_cli_as_real_cross_language_app_flow(tmp_path):
    (tmp_path / "launcher.js").write_text(
        "const { spawn } = require('child_process');\n"
        "function launch() { return spawn('worker.py'); }\n",
        encoding="utf-8",
    )
    (tmp_path / "worker.py").write_text(
        "def run():\n"
        "    return 1\n\n"
        "if __name__ == '__main__':\n"
        "    run()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), framework="none")
    launch = _node(graph, "launch", "javascript")
    worker_module = _node(graph, "worker", "python")

    assert _has_edge(graph, launch, worker_module, EdgeKind.SPAWNS)


def test_javascript_multiple_functions_and_local_calls_are_mapped(tmp_path):
    (tmp_path / "app.js").write_text(
        "function parseData() { return 1; }\n"
        "function loadData() { return parseData(); }\n"
        "class Controller {\n"
        "  refresh() { return loadData(); }\n"
        "}\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), framework="none")
    parse_data = _node(graph, "parseData", "javascript")
    load_data = _node(graph, "loadData", "javascript")
    refresh = _node(graph, "refresh", "javascript")

    assert _has_edge(graph, load_data, parse_data, EdgeKind.CALLS)
    assert _has_edge(graph, refresh, load_data, EdgeKind.CALLS)
