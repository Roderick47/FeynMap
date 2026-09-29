# P1.5 — Flask registered Blueprint prefix composition

**Status: accepted** — [external workflow 36523511644](https://github.com/Roderick47/FeynMap/actions/runs/36523511644) and [Python 3.8/3.12 + recursive self-check 36523511531](https://github.com/Roderick47/FeynMap/actions/runs/36523511531) passed.

**Scope:** Static declaration -> import identity -> registration -> decorator
composition for Flask endpoints. The language parser and FeynMap's generic
integration contracts remain language-neutral; no Flask imports or runtime
execution of the target repository are required.

## Truth model

A decorator such as @bp.route('/tokens') proves only that a Blueprint
declares a route fragment. It does NOT establish an exposed /tokens HTTP
endpoint. Its declared fragment is kept in
graph.metadata['flask_blueprint_composition'], version 1.0.0.

Emit a supported http_server integration contract only when:
1. A Blueprint identity is statically grounded in a Flask Blueprint(...)
   constructor (including imports and aliases).
2. The exact Blueprint identity is passed to register_blueprint() on a
   statically created Flask application (possibly through statically composed
   nested Blueprint registrations).
3. Its effective prefix is literal and unambiguous, using registration
   url_prefix when supplied or the declaration's default otherwise.
4. The decorator's rule and methods are static and supported.

Each resulting contract records the exact route target, method(s), source
decorator path/line, Blueprint identity and declaration path/line, effective
prefix, registration path/line/chain, derivation and static provenance. A
direct decorator on a statically identified Flask app remains a direct route.

Unregistered Blueprints, dynamic prefix/method/rule expressions, unknown
import identities and unknown decorator hosts are recorded as unresolved.
They never create a pretend raw HTTP server route. One Blueprint can
produce multiple qualified endpoints if actually registered more than once.
Nested Blueprint prefixes are composed only along Flask-registered paths.

P1.5 replaces only the existing Flask decorator HTTP pass; FastAPI's
generic decorator analysis and all Django semantics remain separate. Its
diagnostic metadata persists through multi-language merge and snapshot.

## Acceptance

Pinned immutable Microblog revision
a975ef64864354867c88e0ed3a17ba7d17dca752:
- app/api/__init__.py declares bp = Blueprint('api', __name__).
- app/__init__.py create_app statically imports the same bp identity and
  registers it with url_prefix='/api'.
- app/api/tokens.py get_token POST and revoke_token DELETE are both exposed
  as /api/tokens, with exact source decorator and registration evidence.
- Neither is erroneously exposed as an independent /tokens server endpoint.

The independent two Microblog probes pass **2/2**, up from 0/2, without modifying the P1.1a
manifest. Across the 11 locked external probes, results improve **8/11 → 10/11**.
MDN remains 6/6 and DRF remains 2/3. Existing MDN 6/6, DRF 2/3, P1.2/P1.3/P1.4 gates, Python 3.8/3.12
tests and recursive self-analysis must stay green.

Synthetic negative fixtures cover unregistered Blueprints, dynamic prefix,
dynamic routes/methods, unrelated fake register_blueprint calls and
same-named variables in different modules. Positive fixtures cover aliased
Blueprint and Flask imports (including imported Flask application instances
and package-relative factory imports), default-vs-override prefixes, root
routes, multiple registrations and nested Blueprint composition.

**Deferred:** runtime-created Blueprints and dynamically supplied prefixes
are not represented as supported endpoint routes; expand support only with
actual evidence and independent probes.
