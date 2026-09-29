"""P1.5: source-authored Flask Blueprint registration and prefix regression tests."""
from pathlib import Path

from feynmap.core import SemanticGraph
from feynmap.engine import FeynMapEngine
from feynmap.integration import contracts
from feynmap.p1_external_baseline import _source_probes


def _write(root: Path, files) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _analyze(root: Path):
    return FeynMapEngine().analyze(str(root), framework="flask")


def _node(graph, name):
    found = [node for node in graph.nodes if node.qualified_name == name]
    assert len(found) == 1, (name, [node.qualified_name for node in found])
    return found[0]


def _servers(graph, qualified):
    return contracts(_node(graph, qualified), "http_server")


def _microblog():
    return {
        "app/__init__.py": (
            "from flask import Flask\n"
            "def create_app():\n"
            "    app = Flask(__name__)\n"
            "    from app.api import bp as api_bp\n"
            "    app.register_blueprint(api_bp, url_prefix='/api')\n"
            "    return app\n"
        ),
        "app/api/__init__.py": (
            "from flask import Blueprint\n"
            "bp = Blueprint('api', __name__)\n"
            "from app.api import tokens\n"
        ),
        "app/api/tokens.py": (
            "from app.api import bp\n"
            "@bp.route('/tokens', methods=['POST'])\n"
            "def get_token(): return {'token': 'abc'}\n"
            "@bp.route('/tokens', methods=['DELETE'])\n"
            "def revoke_token(): return '', 204\n"
        ),
    }


def test_microblog_blueprint_registration_composes_exact_path_and_methods(tmp_path):
    _write(tmp_path, _microblog())
    graph = _analyze(tmp_path)
    post = _servers(graph, "app.api.tokens.get_token")
    delete = _servers(graph, "app.api.tokens.revoke_token")
    assert [(item["target"], item["methods"]) for item in post] == [
        ("/api/tokens", ["POST"]),
    ]
    assert [(item["target"], item["methods"]) for item in delete] == [
        ("/api/tokens", ["DELETE"]),
    ]
    assert all(item["derivation"] == "flask.blueprint.registered_route"
               and item["evidence_kind"] == "static" for item in post + delete)
    assert all(item["registration_file"] == "app/__init__.py"
               and item["registration_line"] == 5 for item in post + delete)
    assert all(item["source_file"] == "app/api/tokens.py" for item in post + delete)
    assert not any(item["target"] == "/tokens" for item in post + delete)

    for symbol, method in (("get_token", "POST"), ("revoke_token", "DELETE")):
        result = _source_probes(graph, {
            "category": "http_route", "source_file": "app/api/tokens.py",
            "source_symbol": symbol, "expected_path": "/api/tokens",
            "expected_method": method,
        })
        assert result["passed"], result
    data = graph.metadata["flask_blueprint_composition"]
    assert data["version"] == "1.0.0"
    assert len(data["blueprints"]) == 1
    assert len(data["emitted_routes"]) == 2
    restored = SemanticGraph.from_dict(graph.to_dict())
    assert restored.metadata["flask_blueprint_composition"] == data


def test_unregistered_blueprint_never_fabricates_exposed_raw_endpoint(tmp_path):
    files = _microblog()
    files["app/__init__.py"] = "from flask import Flask\ndef create_app(): return Flask(__name__)\n"
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    assert _servers(graph, "app.api.tokens.get_token") == []
    assert _servers(graph, "app.api.tokens.revoke_token") == []
    data = graph.metadata["flask_blueprint_composition"]
    assert len(data["declared_routes"]) == 2
    assert len(data["emitted_routes"]) == 0
    assert sum(item["reason"] == "blueprint_not_statically_registered"
               for item in data["unresolved"]) == 2


def test_dynamic_registration_prefix_stays_unknown_not_raw(tmp_path):
    files = _microblog()
    files["app/__init__.py"] = (
        "from flask import Flask\n"
        "def create_app(prefix):\n"
        "    app = Flask(__name__)\n"
        "    from app.api import bp as api_bp\n"
        "    app.register_blueprint(api_bp, url_prefix=prefix)\n"
        "    return app\n"
    )
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    assert _servers(graph, "app.api.tokens.get_token") == []
    assert any(item["reason"] == "dynamic_registration_prefix"
               for item in graph.metadata["flask_blueprint_composition"]["unresolved"])


def test_declared_prefix_default_and_explicit_override(tmp_path):
    files = {
        "web/__init__.py": (
            "from flask import Blueprint as Group\n"
            "bp = Group('web', __name__, url_prefix='/default')\n"
        ),
        "web/routes.py": (
            "from . import bp as group\n"
            "@group.get('/')\n"
            "def index(): return 'ok'\n"
            "@group.post('/save')\n"
            "def save(): return 'ok'\n"
        ),
        "app.py": (
            "from flask import Flask\n"
            "from web import bp as web_bp\n"
            "app = Flask(__name__)\n"
            "app.register_blueprint(web_bp)\n"
            "app.register_blueprint(web_bp, url_prefix='/override', name='second')\n"
        ),
    }
    _write(tmp_path, files)
    graph = _analyze(tmp_path)
    assert {tuple([item["target"]] + item["methods"])
            for item in _servers(graph, "web.routes.index")} == {
        ("/default/", "GET"), ("/override/", "GET"),
    }
    assert {item["target"] for item in _servers(graph, "web.routes.save")} == {
        "/default/save", "/override/save",
    }
    assert all(item["url_prefix"] in {"/default", "/override"}
               for item in _servers(graph, "web.routes.index"))


def test_two_different_blueprint_identities_and_alias_imports_are_not_conflated(tmp_path):
    _write(tmp_path, {
        "one/__init__.py": "from flask import Blueprint\nbp = Blueprint('one', __name__)\n",
        "two/__init__.py": "from flask import Blueprint\nbp = Blueprint('two', __name__)\n",
        "one/routes.py": "from one import bp\n@bp.route('/same')\ndef one(): return 'one'\n",
        "two/routes.py": "from two import bp\n@bp.route('/same')\ndef two(): return 'two'\n",
        "app.py": (
            "from flask import Flask\n"
            "from one import bp as first\n"
            "from two import bp as second\n"
            "app = Flask(__name__)\n"
            "app.register_blueprint(first, url_prefix='/one')\n"
            "app.register_blueprint(second, url_prefix='/two')\n"
        ),
    })
    graph = _analyze(tmp_path)
    assert [item["target"] for item in _servers(graph, "one.routes.one")] == [
        "/one/same",
    ]
    assert [item["target"] for item in _servers(graph, "two.routes.two")] == [
        "/two/same",
    ]


def test_non_flask_registration_call_and_unrelated_decorator_not_endpoints(tmp_path):
    _write(tmp_path, {
        "api/__init__.py": "from flask import Blueprint\nbp = Blueprint('api', __name__)\n",
        "api/views.py": (
            "from api import bp\n"
            "@bp.route('/example')\n"
            "def example(): return 'ok'\n"
        ),
        "app.py": (
            "from api import bp\n"
            "class Other:\n"
            "    def register_blueprint(self, value, url_prefix): pass\n"
            "other = Other()\n"
            "other.register_blueprint(bp, url_prefix='/fake')\n"
        ),
        "other.py": (
            "class Unrelated:\n"
            "    def route(self, *args, **kwargs): return lambda fn: fn\n"
            "not_flask = Unrelated()\n"
            "@not_flask.route('/bad')\n"
            "def fake(): return 'not an endpoint'\n"
        ),
    })
    graph = _analyze(tmp_path)
    assert _servers(graph, "api.views.example") == []
    assert _servers(graph, "other.fake") == []


def test_direct_flask_app_route_stays_visible_without_blueprint(tmp_path):
    _write(tmp_path, {
        "app.py": (
            "from flask import Flask as Application\n"
            "app = Application(__name__)\n"
            "@app.route('/health', methods=['GET'])\n"
            "def health(): return 'ok'\n"
        ),
    })
    graph = _analyze(tmp_path)
    routes = _servers(graph, "app.health")
    assert [(item["target"], item["methods"]) for item in routes] == [
        ("/health", ["GET"]),
    ]
    assert routes[0]["derivation"] == "flask.application.direct_route"


def test_dynamic_methods_or_route_fragment_never_promoted(tmp_path):
    _write(tmp_path, {
        "app.py": (
            "from flask import Flask, Blueprint\n"
            "app = Flask(__name__)\n"
            "bp = Blueprint('api', __name__)\n"
            "app.register_blueprint(bp, url_prefix='/api')\n"
            "@bp.route('/dynamic-method', methods=choices)\n"
            "def invalid_methods(): return ''\n"
            "@bp.route(fragment, methods=['POST'])\n"
            "def invalid_route(): return ''\n"
        ),
    })
    graph = _analyze(tmp_path)
    assert _servers(graph, "app.invalid_methods") == []
    assert _servers(graph, "app.invalid_route") == []
    assert any(item["reason"] == "dynamic_or_invalid_route_or_methods"
               for item in graph.metadata["flask_blueprint_composition"]["unresolved"])


def test_nested_blueprint_registration_composes_parent_and_child(tmp_path):
    _write(tmp_path, {
        "app.py": (
            "from flask import Flask, Blueprint\n"
            "app = Flask(__name__)\n"
            "parent = Blueprint('parent', __name__)\n"
            "child = Blueprint('child', __name__, url_prefix='/child')\n"
            "parent.register_blueprint(child)\n"
            "app.register_blueprint(parent, url_prefix='/v1')\n"
            "@child.route('/ping')\n"
            "def ping(): return 'pong'\n"
        ),
    })
    graph = _analyze(tmp_path)
    routes = _servers(graph, "app.ping")
    assert [item["target"] for item in routes] == ["/v1/child/ping"]
