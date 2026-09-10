# Language-neutral relationship evaluation

The new `evaluate_graph(graph, annotations)` API and `feynmap evaluate` command
score any canonical `SemanticGraph` against explicit labels. The evaluator does
not import an adapter, parse a language, use Python-qualified-name conventions,
or assume that the source and target have the same language. Language and path
are optional exact-match selector fields, not special cases.

This is a benchmark foundation, not a claim that all languages are supported by
the analyzer. Current source adapters remain Python, HTML, and JavaScript. A
future language adapter can use the same evaluator without changing it.

## Run the included benchmark

From a checkout with FeynMap installed:

```bash
feynmap analyze tests/fixtures/benchmark_mixed --output /tmp/mixed.semantic.json
feynmap evaluate /tmp/mixed.semantic.json tests/fixtures/benchmark_mixed/annotations.json
```

Evaluation does not reparse or execute repository source. It accepts graph JSON,
so external graph producers can use it too. Exit code 0 means the labeled fixture
passed; 1 means missing symbols, missed positive relationships, or emitted
negative relationships. Invalid annotations or malformed graph identities are
rejected rather than silently scored.

Python API:

```python
from feynmap import evaluate_graph
report = evaluate_graph(graph, annotations)
```

## Annotation contract

```json
{
  "schema": "feynmap.relationship_benchmark.v1",
  "name": "Example",
  "symbols": {
    "client": {"name": "loadItems", "language": "javascript"},
    "handler": {"name": "items", "language": "python", "path": "app.py"}
  },
  "relationships": [
    {"source": "client", "target": "handler", "kind": "requests", "present": true},
    {"source": "handler", "target": "client", "kind": "calls", "present": false}
  ]
}
```

Selectors require at least one of `id`, `name`, or `qualified_name`; optional
`language` and `path` fields narrow the match. Every supplied field must match
exactly, including case. Names are opaque strings. Ambiguous selectors, duplicate
or contradictory labels, relation typos, and non-boolean labels are errors.
Different aliases resolving to the same pair cannot double-count a judgment.

Negative labels must be explicitly justified by the fixture's behavior and scope.
The absence of an edge in FeynMap's output is never itself a reason to label a
relationship negative.

## Metrics and honest limits

- **True positive:** an annotated positive relationship was emitted.
- **False negative:** a positive relationship was missed, including missing endpoints.
- **False positive:** an explicitly negative relationship was emitted.
- **True negative:** an explicitly negative relationship was absent, with both endpoints present.
- **Unscorable negative:** an endpoint was missing. This cannot earn true-negative credit.
- **Labeled precision:** TP / (TP + FP); **labeled recall:** TP / (TP + FN).
- Zero denominators return null, not an invented perfect score.
- Unlabeled relationships are reported as **unjudged**, not false positives.
- Duplicate detector edges count once per source/kind/target relationship.
- Per-language-pair metrics use the same definitions, including cross-language pairs.
- Per-tier observations show correct/incorrect labeled emitted relationships and
  sample sizes. These are small-sample observations, not calibrated probabilities.

The report includes each judgment and matching edge IDs for inspection. It does
not mutate the graph. Input order does not change results.

## Included fixtures and results

The source fixture is hand-authored Python + HTML + JavaScript. Its six positive
labels cover backend calls, frontend calls, template rendering, script loading,
event invocation, and a frontend-to-backend HTTP request. Two negatives cover an
idle function and a nonexistent cross-language helper call. Both languages use a
function named `helper`, deliberately exercising exact language-specific selection
without adding language-specific logic to evaluation.

The fixture finds all six positive relationships and emits neither negative.
An injection test adds the nonexistent helper edge and confirms that the evaluator
reports a false positive. Other tests use arbitrary future-language names, missing
endpoints, ambiguous selectors, duplicate annotations, and unjudged edges.

These are regression fixtures developed with the tool, **not an independently
curated corpus**. They establish metric behavior and a small cross-language gate;
they do not establish production accuracy, recall, or model-answer quality.

## Next validation work

Expand reviewed source fixtures with lexical shadowing, dynamic imports, nested
routes, service boundaries, and parser failures. Keep expected labels sourced
from code review rather than graph output. Add independently reviewed real-world
repositories and retain both positive and negative examples before adjusting
confidence thresholds. The existing self-hosting benchmark remains a separate
compatibility test; it is not silently replaced by the new metrics.
