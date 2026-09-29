# P1 — Small, testable framework-semantic checkpoints

Status: P1.1a source corpus pinned; P1.1b baseline execution is next.

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

**P1.1b — execute the baseline (next).** Checkout exactly those commits
in clean isolated folders; run the same FeynMap `main` build over each repo;
capture graph symbols, relevant relationship/evidence diagnostics, routes,
resource usage, and selected context. Emit a machine-readable report. Do not
block the CI job simply because a known semantic probe currently fails;
separate 'analysis crashed' from 'probe not yet supported'. These baseline
gaps become P1.2–P1.6 regression targets.

## P1.2 — Django model and template grounding

- Recognize class-level `model`, `queryset` and explicit `template_name` on
  supported CBVs using import-aware symbol resolution.
- Infer Django's known default CBV template names only when the convention
  and model identity are evidenced; label inferred vs explicit relationships.
- Test both an independently pinned MDN example and source-authored tiny
  fixtures including ambiguous imported model names.
- Gate: expected model/template relations appear; no unsupported relation is
  invented; preserved graph contracts and downstream impact tests pass.

## P1.3 — Django AppConfig hub semantics

- Separate app lifecycle/membership from task-relevant behavioral dependency.
- Preserve provenance for framework membership without promoting every handler
  into an unrestricted `DEPENDS_ON` hub across sparse routing.
- Gate: impact on Book lists actual model/view dependencies rather than only
  app infrastructure; independent membership tests remain intact.

## P1.4 — Django named URL graph

- Connect `path` and supported static `reverse`, `reverse_lazy` and `{% url %}`
  references using namespace-aware route names.
- Dynamic unknown expressions remain unresolved; template literal text is
  not treated as an HTTP client URL.
- Gate: independent named-route/reversal fixtures have correct targets and
  source-backed confidence; unknown names do not become fabricated edges.

## P1.5 — Flask registered Blueprint prefix composition

- Resolve Blueprint identities to actual registration sites; combine static
  registration `url_prefix` with individual decorator paths.
- Gate: pinned Microblog `get_token` POST and `revoke_token` DELETE both map
  to `/api/tokens`; unregistered/dynamic prefixes remain explicitly unknown.

## P1.6 — DRF and diagnostic accuracy

- Ground serializer/model bindings, permission classes and routed/unrouted
  handler coverage with explicit source evidence.
- Distinguish genuinely unresolved integration targets, legitimate server
  endpoints without in-repo clients, unknown dynamic calls and Python
  built-ins; make raw versus actionable diagnostic counts transparent.
- Gate: pinned DRF probes stop treating ordinary framework/intrinsic behavior
  as actionable missing relationships.

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
