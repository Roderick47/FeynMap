# P1.4 — Source-backed Django named URL resolution

**Status: accepted** — [external workflow 36522700164](https://github.com/Roderick47/FeynMap/actions/runs/36522700164) and the Python 3.8/3.12 + recursive self-check suites are green.

Scope: static Django URL registrations, include() prefix/namespace composition,
Python reverse()/reverse_lazy() and literal Django template {% url %} tags.
No third-party Django code is imported or run. Source-authoritative and
framework-inferred relationships stay distinct.

## Representation

- Inspect literal urlpatterns declared with imported django.urls.path/re_path.
- Trace imported handler identity exactly (e.g. from . import views as screens,
  or from .views import BookListView as Listing). A same-named symbol elsewhere
  in the repository is never accepted by name proximity alone.
- Trace literal include('module.urls'), optional (module, app_name) tuples and
  namespace=, using child app_name as Django's default instance namespace.
  Static HTTP route contracts keep the bare declaration name, fully qualified
  route_name, composed route, source registration file/line and static provenance.
- Store the accepted registration ledger and unresolved observations in
  graph.metadata['django_named_urls'] version 1.0.0. Carry metadata through
  the multi-language graph merge and semantic snapshot serialization.
- Python reverse()/reverse_lazy() references are captured only when imported
  from Django's URL package (including aliases), with a literal named target.
  Non-Django same-named functions and dynamic expressions cannot invent edges.
- The generic HTML adapter preserves literal Django {% url 'name' %} as a
  django_url_reverse contract. It does not turn a template expression into an
  HTTP client URL, and masks template comment/verbatim blocks and HTML comments.
- At graph integration, a named reference creates ROUTES_TO only if exactly
  one registration bears that full qualified name. A bare 'books' reference
  does NOT incorrectly match a 'catalog:books' registration. Unknown, dynamic,
  unsupported includes, and duplicate full names remain unresolved.

The ROUTES_TO relationship means "this static named URL expression resolves
to this in-repository handler under the accepted static URLconf". It is not
evidence that a user made an HTTP request or that every runtime middleware,
app registration or dynamic URL mutation has been reproduced.

## Acceptance

P1.4 turns the independent, immutable MDN named-url-books probe from
missing into matched, with source registration at catalog/urls.py line 8,
name 'books', include-composed target /catalog/books/, confidence >= 0.9, explicit static derivation
django.urls.static_registration. The pinned MDN probes now pass 6/6 (previously 5/6), and the frozen
11-probe corpus passes 8/11 (previously 7/11).
Existing P1.2 five relations and P1.3
29/20 structural memberships with zero manufactured dependency hubs remain
hard external replay gates. Microblog/DRF unresolved probes are not silently
changed to appear passed.

Synthetic regressions cover:
- aliases and qualified imported handler identities, unrelated same-named views;
- include() route prefix composition, app_name and explicit namespaces;
- source-backed Python reverse, reverse_lazy and template URL references;
- unknown and dynamic names, duplicate full names and non-Django reverse;
- no template-as-http-client false positives, masked comments and snapshots;
- static urlpatterns rather than unrelated path() calls.

Implementation: feynmap/adapters/frameworks/django_urls.py,
feynmap/adapters/frameworks/django.py, feynmap/adapters/html.py,
feynmap/integration.py, feynmap/repository.py,
tests/test_django_named_urls.py, and external replay CI.

Deferred by design: dynamic URLconf programming, regex reverse argument solving,
runtime middleware URL rewriting, and Flask Blueprint composition (P1.5).
