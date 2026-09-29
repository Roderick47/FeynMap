# P1.1b — Reproducible external semantic baseline

**Status:** Complete. Captured from the unchanged post-P0 FeynMap analyzer on
29 September 2026 (functional revision `31d33c23`). The 11 expected facts
were locked in P1.1a before running the tool. No adapter, ranking, or production
routing behavior was changed to obtain these baseline results.

**Full artifacts:** [GitHub Actions run 36506425924](https://github.com/Roderick47/FeynMap/actions/runs/36506425924).
The per-repository JSON reports include all observed nodes, evidence tiers,
candidate edges, raw integration contracts, selected context, route choices,
diagnostic samples, elapsed time, and process peak RSS. A durable condensed
machine-readable copy is at
`experiments/results/p1_1b_20260929_external_baseline.json`.

## Reproduction contract

Every job checked out a public repository at the precise 40-character SHA
frozen in `experiments/p1_external_framework_manifest.json`. It verified
`git rev-parse HEAD` before analysis. Only FeynMap was installed; third-party
repository dependencies and source code were never executed.

- Python 3.12, GitHub-hosted Linux runner, one independent process per fixture.
- `FeynMapEngine.analyze(path, language="auto", framework=manifest["framework"])`.
- Source relationships: compare the unique named semantic node to a named
  target through an actual matching edge; merely having both files or a broad
  import edge does not pass.
- Django named URL probe: the manifest records the *registration file*
  `catalog/urls.py`; resolve the same-app handler in `catalog/views.py`
  before inspecting its source-backed HTTP contract.
- Retrieval: `SparseContextPipeline.concept` with an ordinary 3,200-token,
  24-node, 24-edge minimal-context budget, deterministic/no external provider.
  Required implementation files must actually be in the delivered context.
- Ingestion: exercise the JavaScript adapter on DRF's pinned static files and
  preserve its original skip diagnostics before independently validating the
  returned graph. The existing `graph.validate()` overwrites diagnostics,
  which is a separate diagnostic-lifecycle follow-up for P1.6.

A missing semantic expectation is *reported*, not converted into a passing CI
result. An analysis crash, missing report, mismatched SHA, or malformed report
does fail CI.

## Measured baseline

| Repository | Nodes | Edges | Source expectations met | Parse + framework analysis | Process peak RSS |
|---|---:|---:|---:|---:|---:|
| MDN Django Local Library | 266 | 581 | **0/6** | 178.6 ms | 29,224 KB |
| Flask Microblog | 279 | 607 | **0/2** | 166.4 ms | 29,868 KB |
| Django REST Framework | 4,128 | 8,040 | **2/3** | 2,328.6 ms | 102,024 KB |
| **Total** | | | **2/11** | | |

These are single-run observations, not repeated-run latency distributions or
whole-product accuracy scores. Peak RSS is the entire analysis process's
high-water mark, not the isolated graph's memory footprint.

### MDN — six unmet expectations

1. `BookListView.model = Book` lacks an evidenced view-to-model semantic edge.
2. `BookDetailView.model = Book` has the same gap.
3. The conventional `catalog/book_list.html` template is not linked from its CBV.
4. The conventional `catalog/book_detail.html` template is not linked from its CBV.
5. The explicitly declared
   `LoanedBooksByUserListView.template_name = 'catalog/bookinstance_list_borrowed_user.html'`
   is not linked as a rendered template.
6. The HTTP route for `BookListView` is present as `/books/` with source
   `catalog/urls.py`, but the registered URL name `books` is absent from
   the handler's contract.

The graph also contains **29** handler-to-AppConfig membership/dependency
edges. This supports investigating whether such broad structural edges crowd
out task-specific relationships; it does *not* establish that every such edge
is factually wrong.

### Flask Microblog — two unmet expectations

`get_token` and `revoke_token` have HTTP contracts with the correct
individual methods (`POST`, `DELETE`), but each uses the decorator's raw
`/tokens` path. Static registration
`app.register_blueprint(api_bp, url_prefix='/api')` is not composed into the
expected final path `/api/tokens`.

### DRF — two met and one unmet expectation

- **Met:** The throttling query delivers
  `rest_framework/throttling.py`. Its selected context contains ten
  non-test nodes and one test node.
- **Unmet:** The serializer query delivers `rest_framework/serializers.py`
  but omits essential `rest_framework/fields.py`. Eight of its ten
  delivered nodes are tests; two are non-test nodes. **These figures count
  nodes, not token percentages.**
- **Met:** The adapter skips both real vendored minified bundles
  (`bootstrap.min.js` and `jquery-3.7.1.min.js`) without crashing and
  records their skip diagnostics.

## Raw diagnostics are not failure counts

The current integration metadata reports 36 raw unresolved contracts for MDN,
40 for Microblog and 49 for DRF; the DRF graph also has 20 AppConfig edges.
An HTTP server with no in-repository client is not inherently a broken
integration. P1.6 must separate external/unreferenced endpoints, built-ins,
genuinely unresolved targets, and actionable failures before interpreting those
numbers as defects.

## What P1.1b establishes—and does not

The known external fixtures reproduce concrete missing framework relationships
and an implementation-vs-test delivery problem without relying on FeynMap's
self-hosting scores. This justifies P1.2–P1.6.

P1.1b is not an AI repair experiment, does not demonstrate downstream
hallucination reduction, and must **not** be reused as the sealed, previously
unseen S7 repair corpus. No expectations should be weakened after observing
FeynMap output.

**Next:** P1.2, starting with Django CBV `model` and `template_name` / default
template conventions. Re-run the immutable P1.1b report after each semantic
change while retaining the original baseline as evidence.
