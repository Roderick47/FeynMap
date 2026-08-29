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


def test_resolver_supports_non_web_cross_language_channels():
    producer = SemanticNode("js", "desktop", NodeKind.FUNCTION, language="javascript")
    worker = SemanticNode("py", "worker", NodeKind.MODULE, language="python")
    publisher = SemanticNode("rust", "publisher", NodeKind.FUNCTION, language="rust")
    subscriber = SemanticNode("java", "subscriber", NodeKind.METHOD, language="java")
    ffi_user = SemanticNode("swift", "nativeCall", NodeKind.FUNCTION, language="swift")
    ffi_export = SemanticNode("cpp", "native_call", NodeKind.FUNCTION, language="cpp")
    writer = SemanticNode("writer", "writer", NodeKind.FUNCTION, language="python")
    reader = SemanticNode("reader", "reader", NodeKind.FUNCTION, language="javascript")

    add_contract(producer, "process_spawn", "worker.py")
    add_contract(worker, "cli_entrypoint", "worker.py")
    add_contract(publisher, "queue_publish", "orders.created")
    add_contract(subscriber, "queue_subscribe", "orders.created")
    add_contract(ffi_user, "ffi_import", "native_call")
    add_contract(ffi_export, "ffi_export", "native_call")
    add_contract(writer, "file_write", "shared/data.json")
    add_contract(reader, "file_read", "shared/data.json")

    graph = SemanticGraph(nodes=[producer, worker, publisher, subscriber, ffi_user, ffi_export, writer, reader])
    IntegrationResolver().resolve(graph)

    assert _has_edge(graph, producer, worker, EdgeKind.SPAWNS)
    assert _has_edge(graph, publisher, subscriber, EdgeKind.EMITS)
    assert _has_edge(graph, ffi_user, ffi_export, EdgeKind.INVOKES)
    assert _has_edge(graph, writer, reader, EdgeKind.FLOWS_TO)
    assert all(edge.attributes.get("integration", {}).get("cross_language") for edge in graph.edges)


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
