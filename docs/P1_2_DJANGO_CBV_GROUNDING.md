# P1.2 — Django class-based-view semantic grounding

**Status:** Complete on the P1.2 feature branch; external acceptance against the
locked P1.1b MDN fixture improves from **0/6 to 5/6** without changing the
Microblog or DRF control results. The remaining MDN failure is the named URL
probe, which belongs to P1.4.

## Scope

P1.2 changes only Django generic class-based-view semantics. It does not
modify AppConfig handling, URL-name/reverse semantics, Flask Blueprint
registration, DRF retrieval policy, Rust routing or the context budget.

## What is now grounded

### Model bindings

Supported Django generic CBVs can now establish a `USES_DATA` edge from a view
to a unique in-repository model when the class body contains an import-resolved
`model = Book` assignment.

Conservative `queryset = Book.objects...` bindings are also recognized for a
small allow-list of ordinary QuerySet chaining methods. FeynMap does not execute
the queryset or infer arbitrary call results.

These relationships use `EvidenceKind.STATIC` and record the assignment line.

### Explicit templates

A literal `template_name = 'catalog/foo.html'` is recorded only when it maps
to exactly one physical template in the repository. The resulting render
relationship retains static source evidence.

If the view overrides `get_template_names()`, uses a dynamic expression, or
the logical template name is absent/ambiguous, FeynMap records the uncertainty
in `node.attributes['django_cbv']['unresolved']` instead of inventing a render
edge.

### Django default-template conventions

For supported generic views (`ListView`, `DetailView`, `CreateView`,
`UpdateView`, `DeleteView`), FeynMap can infer the conventional template name
only when:

- the generic base is proven through an import from Django;
- exactly one in-repo model is grounded from `model` or recognized `queryset`;
- no conflicting grounded model exists;
- no custom queryset/object/template selector makes the default uncertain; and
- the derived logical template maps to one physical repository file.

These edges are deliberately marked as framework-inferred, not as static
source facts.

## False-positive controls

The source-authored test corpus includes:

- import aliases for Django generic bases and model modules;
- ambiguous duplicate model imports;
- unrelated third-party classes also named `ListView`;
- dynamic querysets;
- conflicting `model` and `queryset` bindings;
- custom `get_template_names()` and dynamic `template_name` expressions;
- missing and duplicate logical template paths; and
- `TemplateView` with an explicit template but no model.

In each uncertain case the expected behavior is **no fabricated relationship**.

## External acceptance

Frozen P1.1b MDN Local Library revision:
`92f1c1e7bdd4ada5209a3c69876ce29e6cee3d96`.

| Probe | P1.1b | P1.2 |
|---|---|---|
| `BookListView -> Book` | missing | **matched** |
| `BookDetailView -> Book` | missing | **matched** |
| `BookListView -> catalog/book_list.html` | missing | **matched** |
| `BookDetailView -> catalog/book_detail.html` | missing | **matched** |
| explicit borrowed-books template | missing | **matched** |
| named URL `books` | missing | missing (P1.4) |

Graph node count remains 266. Edge count increases from 581 to 635 because
the Django CBV pass contributes grounded model and template semantics across
the repository, not only the five scored fixture relations.

The external controls remain unchanged:

- Flask Microblog: 0/2 (Blueprint prefix still P1.5).
- Django REST Framework: 2/3 (serializer implementation context remains P2).

The CI baseline workflow now explicitly gates the five P1.2 MDN probe IDs so
future changes cannot silently regress them.

## Implementation

- `feynmap/adapters/frameworks/django_cbv.py` — isolated source-only CBV pass.
- `feynmap/adapters/frameworks/django.py` — invokes CBV enrichment before
  AppConfig/URL/template-call enrichment.
- `tests/test_django_cbv_semantics.py` — source-authored positive and negative
  cases.
- `.github/workflows/p1-external-baseline.yml` — immutable external P1.2 gate.
- `experiments/results/p1_2_20260929_django_cbv.json` — machine-readable delta.

## Why this design

The P1.1 review showed that higher-level routing cannot recover relationships
that do not exist in the graph. P1.2 therefore improves graph truth first and
keeps uncertainty explicit. It intentionally prefers missing an unprovable
relationship over creating a plausible but unsupported one.

**Next:** P1.3 — keep Django AppConfig lifecycle/membership evidence while
preventing its broad handler hub from behaving like an ordinary task-relevant
`DEPENDS_ON` relationship.
