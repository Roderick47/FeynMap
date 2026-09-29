# P1 — Small, testable framework-semantic checkpoints

Status: P1.1–P1.6 complete; P1.7 frozen external replay and acceptance is next.

Do NOT one-shot P1: each phase changes FeynMap's graph truth, so regression risk compounds if model, template, URL, Flask and DRF changes are mixed into one implementation.

## P1.1 — Independent external baseline (two substeps)

**P1.1a — freeze fixtures (done).** The source-authored manifest
`experiments/p1_external_framework_manifest.json` pins exact commits of
three public repositories and explicit expected facts. These are newly chosen
pinned revisions, not claimed to be the precise commits Claude reviewed.

| Fixture | Immutable commit | Priority evidence |
|---|---|---|
| MDN django-locallibrary-tutorial | `92f1c1e7bdd4ada5209a3c69876ce29e6cee3d96` | `BookListView.model = Book`; default and explicit CBV template links; named route |
| Miguel Grinberg microblog | `a975ef64864354867c88e0ed3a17ba7d17dca752` | Blueprint `/api` + `/tokens` produces `/api/tokens` for POST and DELETE |
| Django REST Framework | `b578eab1cad040414b758131af1e17aa000b51e2` | Throttling implementation recall; serializer implementation recall; vendored JS must not crash |

The manifest contains 11 source-authored probes. Its outcomes are expectations
derived from explicit source code or documented framework conventions, NOT
results produced by FeynMap itself. The current recorded baseline should
report failures transparently rather than silently weakening expectations.

**P1.1b — external baseline (done).** All three commits were independently
checked out and verified before static analysis. A dedicated CI matrix runs
`feynmap.p1_external_baseline` against those checkouts, capturing source
nodes/edges/contracts, route and selected-context evidence, diagnostics,
time and process peak RSS. The fixture collection validates report and
revision integrity without treating a known missing relationship as a CI error.
A completed analysis error still fails CI.

The locked initial result is **2/11 probes met** (MDN 0/6, Microblog 0/2,
DRF 2/3), with no analysis crashes. Read
`docs/P1_1B_EXTERNAL_BASELINE_RESULTS.md` and the permanent machine-readable
`experiments/results/p1_1b_20260929_external_baseline.json`; full raw
per-repository reports are artifacts from
[workflow run 36506425924](https://github.com/Roderick47/FeynMap/actions/runs/36506425924).
The old baseline must never be retroactively replaced with post-P1.2 results.

## P1.2 — Django model and template grounding (done)

Implemented as an isolated static pass in `django_cbv.py`. Class-level
`model`, conservative `queryset`, explicit `template_name`, and supported
generic-view default template conventions now resolve only when imports,
in-repository model identity and physical template identity are unambiguous.

The frozen MDN fixture improves from **0/6 to 5/6** P1 probes. The five P1.2
facts are now explicit external CI gates. The remaining named URL belongs to
P1.4; Flask and DRF controls remain unchanged.

Negative fixtures cover unrelated same-named generic bases, ambiguous model
imports, dynamic/conflicting querysets, custom template selection and missing
or ambiguous templates. Those cases stay unresolved rather than becoming
speculative edges.

See `docs/P1_2_DJANGO_CBV_GROUNDING.md` and
`experiments/results/p1_2_20260929_django_cbv.json`.

## P1.3 — Django AppConfig hub semantics (done)

Remove the synthetic handler→AppConfig `DEPENDS_ON` edges. Retain the source
directory association separately in additive graph metadata, with its original
source location, inferred evidence tier, unique nearest-match handling and
unresolved equally near associations. This is not proof of runtime app
registration. The metadata persists across mixed-language graph merges and
snapshot serialization but is not traversed as a behavioral relationship.

Pinned P1.3 replay: MDN keeps 29 inferred structural memberships with zero
artificial hub edges; DRF keeps 20 with zero artificial hub edges. All five
previous P1.2 MDN relations remain correctly evidenced; total independent
external results remain 7/11. The real MDN Book impact includes BookListView
and BookDetailView; CatalogConfig impact and direct region adjacency no longer
pull in those views solely through membership.

See `docs/P1_3_APPCONFIG_HUB_SEMANTICS.md` and
`experiments/results/p1_3_20260929_appconfig_hub.json`.

## P1.4 — Django named URL graph (done)

Resolve imported handlers from literal urlpatterns and compose static include()
prefixes and namespaces. Static reverse/reverse_lazy and template {% url %}
references make ROUTES_TO edges only when one full name maps to one registered
handler; unsupported/dynamic/ambiguous references retain UNKNOWN. Named
registration contracts preserve source file, line, static derivation, bare name,
and namespace-aware full name. Template tags are not generic HTTP client URLs.

[External replay 36522700164](https://github.com/Roderick47/FeynMap/actions/runs/36522700164):
the independent MDN named-route fact matches /catalog/books/ at
catalog/urls.py line 8, improving MDN 5/6 -> **6/6** and the 11-probe corpus
7/11 -> **8/11**. P1.2's five evidence tiers and P1.3's membership/non-hub
regressions stay green. Flask remains 0/2; DRF 2/3. Python 3.8/3.12 tests
and recursive self-check pass. See docs/P1_4_DJANGO_NAMED_URLS.md.

## P1.5 — Flask registered Blueprint prefix composition (done)

Trace the exact imported Blueprint identity through declaration, registration
on a statically instantiated Flask app and decorated route, including aliased
imports, package-relative factories, direct Flask app routes, multiple and
nested Blueprint registrations. Compose registered url_prefix and rule,
preserving each source file/line and static confidence. Unknown/dynamic and
unregistered routes remain unresolved; do not expose a raw path fragment.

[External replay 36523511644](https://github.com/Roderick47/FeynMap/actions/runs/36523511644):
pinned Microblog POST and DELETE now both map to /api/tokens, improving
Microblog **0/2 -> 2/2** and the 11 external source-authored probes **8/11
-> 10/11**. Previous MDN=6/6, DRF=2/3 and P1.2–P1.4 CI gates persist.
Python 3.8/3.12 + recursive self-check pass. See
docs/P1_5_FLASK_BLUEPRINT_COMPOSITION.md and
experiments/results/p1_5_20260929_flask_blueprints.json.

## P1.6 — DRF source grounding and actionable diagnostics (done)

The static Django DRF pass resolves exact imported/in-repository view
serializer_class, ModelSerializer.Meta.model, literal permission_classes and
proven local policy subclasses. It records class-body field declarations,
literal Meta field lists, validation-method presence and distinct source
registration coverage: proven Django URLs, declared-only DRF router
registrations, and views with no static route proven. No unsupported dynamic
route is fabricated, and no static route does not mean unrouted at runtime.

The pinned DRF SerializerMetaclass._get_declared_fields literally checks
isinstance(obj, Field), with Field imported from rest_framework.fields.
The new evidence-backed method -> Field USES_DATA edge now activates both
rest_framework/serializers.py and rest_framework/fields.py for the locked
serializer query. That does not guarantee final delivery: fields.py remains
omitted by the existing token/node context packer. Distinguishing graph
activation from policy-based delivery preserves the immutable 2/3 DRF result
and the **10/11 overall** source-authored probe result; downstream
implementation-vs-test context budget balancing is explicitly P2.

The unchanged 54 raw unmatched DRF integration contracts are now categorized:
18 potential local-static-target review candidates and 36 normal/unknown
observations, without asserting that either number measures errors. The
generic Python analyzer's 1,069 unresolved built-in calls are recorded in
a separate denominator, not added as missing integration edges. Dynamic
framework observations are separately counted.

The pinned [P1.6 external replay 36525528345](https://github.com/Roderick47/FeynMap/actions/runs/36525528345)
passes the newly required source-backed DRF activation and diagnostic
accounting gates plus every P1.2–P1.5 regression gate.
[Python 3.8/3.12 + recursive self-check 36525528304](https://github.com/Roderick47/FeynMap/actions/runs/36525528304)
pass. Read docs/P1_6_DRF_GROUNDING_AND_DIAGNOSTICS.md and
experiments/results/p1_6_20260929_drf_diagnostics.json.

## P1.7 — External replay and acceptance

- Replay every immutable P1.1 probe against the updated graph.
- Record before/after true positives, false positives, unresolved cases,
  evidence tiers, selected context, implementation recall and runtime.
- Run Python 3.8/3.12, recursive self-analysis, contract conformance and
  error-path tests. Do not accept a 'fix' that simply adds more edges.
- Keep the P1.1 corpus as a development regression set; freeze a completely
  separate S7 held-out AI-agent evaluation dataset.

## Changes deliberately outside P1

Test-vs-implementation context-budget policy (P2); context CLI and optional
MCP integration (P3); agent task-level R1 comparison (S7); packaging migration
(P4); more Rust/language adapters. Preserve Python-default S6.9 behavior.
