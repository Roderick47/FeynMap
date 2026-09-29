# P1.2 — Django class-based-view model and template grounding

**Status: accepted for optional framework enrichment, with the pinned external
P1.1 baseline replayed unchanged.** No Django source is executed or imported.
Implementation: `feynmap/adapters/frameworks/django_cbv.py`, called from the
existing `DjangoAdapter.enrich` stage before language graphs are merged.

## Purpose and source-grounded representation

Previously, even an explicit `BookListView.model = Book` did not give the graph
an evidenced view-to-model relationship. Impact traversal from `Book` therefore
could not find its actual class-based-view consumers. Likewise, template
selection declared as a CBV class attribute was absent from integration.

P1.2 performs four narrow tasks:

1. Identify direct supported Django generic CBV bases by their resolved import
   identity, including local aliases (`from django.views.generic import ListView as CoreList`).
   An unrelated class merely named `ListView` does not qualify.
2. Resolve static direct class assignments `model = Book`, `model: type = Book`,
   and recognized `queryset = Book.objects.filter(...).order_by(...)` chains
   to a uniquely qualified, in-repository Django model node. No global
   same-short-name guessing or dynamic expression evaluation is allowed.
3. Add a `USES_DATA` view → model edge with direct static source evidence,
   including assignment line, qualified target identity and confidence tier
   `supported`. This can be traversed backwards from the model in impact search.
4. Resolve static explicit `template_name` to a unique existing repository
   HTML file and use the existing language-neutral `template_render` integration
   contract to emit `RENDERS`. For known default List/Detail/Create/Update/Delete
   conventions, require an evidenced model, a known app label and a unique
   matching HTML template, then label the route `inferred` rather than
   treating a framework convention as source-level proof.

Explicit template declarations use score 0.98 (`supported` once integrated);
default name conventions use score 0.70 (`inferred` once integrated).
These values are tier/strength annotations, not statistically calibrated
probabilities and not runtime verification.

## Unknown stays unknown

- Ambiguous short names or import aliases, external/dynamic model references,
  and arbitrary queryset factories do NOT acquire fabricated model links.
- An existing but duplicate logical template name does not become an arbitrary
  first-match `RENDERS` edge; missing files also remain unresolved.
- Custom class methods `get_template_names`, `get_queryset` and `get_object`
  block default template inference. A custom `get_template_names` also prevents
  claiming that even an explicit attribute necessarily controls rendering.
- If explicit model and queryset are both statically evidenced but refer to
  different models, their individual source bindings can be represented,
  but default template selection is not inferred.
- Supported direct generic CBVs and repository HTML templates are the current
  scope. Custom transitive CBV inheritance, dynamic Django app labels,
  runtime template-loader paths and third-party injected model definitions
  require additional evidence rather than extrapolation from names.

An in-memory `django_cbv` field on eligible view-node attributes records
which bindings were resolved and why uncertain relationships were skipped.
The existing semantic graph schema and frozen confidence policy were not
changed.

## Pinned external result

Replay of `experiments/p1_external_framework_manifest.json` at the exact
three P1.1 revisions, including MDN Django SHA
`92f1c1e7bdd4ada5209a3c69876ce29e6cee3d96`:

| Repository | P1.1b | P1.2 | Change |
|---|---:|---:|---:|
| MDN Django Local Library | 0/6 | **5/6** | +5 |
| Flask Microblog | 0/2 | 0/2 | unchanged |
| Django REST Framework | 2/3 | 2/3 | unchanged |
| **All original source-authored probes** | **2/11** | **7/11** | **+5** |

Five now independently observed relationships on pinned MDN source:

- `BookListView → Book` (`USES_DATA`, `supported`).
- `BookDetailView → Book` (`USES_DATA`, `supported`).
- `BookListView → catalog/book_list.html` (`RENDERS`, `inferred`).
- `BookDetailView → catalog/book_detail.html` (`RENDERS`, `inferred`).
- `LoanedBooksByUserListView → catalog/bookinstance_list_borrowed_user.html`
  (`RENDERS`, `supported`, explicit source declaration).

MDN retains 266 graph nodes; the edge count rises from 581 to 635 because
several additional recognized CBVs have source-bound models and/or uniquely
resolvable templates. The five locked probes test five selected relationships;
they are not a blanket correctness assessment of all 54 new edges.

**Remaining MDN failure:** the handler route `/books/` exists but its
registered URL name `books` is missing (P1.4). The existing 29 AppConfig
membership dependencies remain deliberately untouched for P1.3.

Microblog retains 279 nodes/607 edges and its two `/api/tokens` gaps for
P1.5. DRF retains 4,128 nodes/8,040 edges and the serializer retrieval gap
for P2, with throttling recall and safe minified-JS skipping still passing.

The repeatable pinned [CI run 36508889343](https://github.com/Roderick47/FeynMap/actions/runs/36508889343)
validates all original probes and *additionally fails* if any of P1.2's
five established MDN relationships disappears or its expected evidence tier
changes. The permanent concise result is
`experiments/results/p1_2_20260929_django_cbv_replay.json`.
The original 2/11 baseline remains stored separately and unmodified.

## Validation and non-goals

Source-authored tests in `tests/test_django_cbv_semantics.py` exercise:
direct and aliased imports, queryset chains, explicit and inferred template
tiering, reverse model-impact traversal, unrelated same-named classes,
ambiguous imports and files, dynamic queryset/template choices, conflicting
bindings and custom rendering methods. Ordinary Python 3.8/3.12 regressions
and recursive FeynMap self-analysis are required.

This phase does not modify AppConfig dependency topology, URL-name reversing,
Flask Blueprint registration or DRF/test-budget ranking, and does not claim
whole-agent repair success. **Next: P1.3 — separate structural AppConfig
membership from behavioral dependencies without losing provenance.**
