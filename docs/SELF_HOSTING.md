# FeynMap Self-Hosting

Phase 1.6 makes FeynMap its own first serious semantic benchmark.

The purpose is not merely to prove that FeynMap can parse its source tree. The benchmark asks a stronger question:

> Does the graph recover architecture facts that we independently know are true about FeynMap?

That distinction prevents a self-evaluation loop in which FeynMap grades only the facts it already knows how to discover.

## Baseline

The Phase 0–1.5 whole-system semantic foundation was merged to `main` at:

```text
4c378e3155b713b2b25bdb1c900c15244b213dad
```

The intended version tag is `v3.0.0-alpha.1`. The repository also preserves a `baseline/v3.0.0-alpha.1` branch at the same commit because the connected automation used during development could not create a true Git tag.

The initial self-hosting foundation and first recursive improvement were later merged at:

```text
bbdf1be4e1aeaa37f08239c9361e8508ab83af35
```

Additional recursive reference points are preserved as branches, including:

- `baseline/self-hosting-pre-type-resolution`
- `baseline/self-hosting-pre-reexport-type-sharing`

These references let later snapshot/diff work compare semantic quality across accepted self-improvement stages.

## Golden architecture

`feynmap/data/feynmap_golden.json` contains architecture facts that should be discoverable independently of the current analyzer implementation. It is included as package data so an installed FeynMap build can evaluate a checked-out FeynMap repository using the same benchmark.

Examples include:

```text
FeynMapEngine.analyze
    CALLS -> merge_language_graphs

FeynMapEngine.analyze
    CALLS -> IntegrationResolver.resolve

FeynMapEngine._select_languages
    CALLS -> AdapterRegistry.detect_languages
    CALLS -> AdapterRegistry.language

FeynMapEngine.analyze
    CALLS -> AdapterRegistry.detect_frameworks
    CALLS -> AdapterRegistry.framework

default_registry
    CALLS -> PythonAdapter
    CALLS -> HTMLAdapter
    CALLS -> JavaScriptAdapter
    CALLS -> DjangoAdapter
    CALLS -> FlaskAdapter
    CALLS -> FastAPIAdapter
```

A missing golden edge is a measured semantic blind spot, not permission to fabricate an edge.

## Running the benchmark

From the FeynMap repository root:

```bash
feynmap self-check .
```

The default report is written to:

```text
feynmap.self-analysis.json
```

An alternate golden file can be supplied:

```bash
feynmap self-check . --golden path/to/golden.json
```

## Measurements

The report records:

- total semantic nodes and edges,
- node/edge counts by kind,
- language distribution,
- evidence-kind distribution,
- confidence-tier distribution,
- evidence coverage,
- parse warnings and graph errors,
- unresolved Python call count,
- functions/methods containing unresolved calls,
- orphan semantic nodes,
- resolved and unresolved integration contracts,
- expected architecture symbol recall,
- expected architecture relationship recall,
- an aggregate architecture score.

Relationships are weighted more heavily than mere symbol presence because architecture is primarily about how components interact.

## Recursive improvement loop

```text
FeynMap source
    ↓
FeynMap self-check
    ↓
semantic graph + quality report
    ↓
missing/ambiguous architecture facts
    ↓
root-cause classification
    ↓
resolver/adapter improvement
    ↓
normal regression tests
    ↓
FeynMap self-check again
    ↓
semantic-quality delta
    ↺
```

Every improvement must preserve FeynMap's uncertainty rule:

> Fewer unresolved relationships are desirable only when new relationships have evidence. Ambiguous relationships must remain unresolved rather than being guessed.

## Recursive improvement 1 — typed instance attributes

The first golden miss was:

```text
FeynMapEngine.analyze
    CALLS -> IntegrationResolver.resolve
```

The source uses `self.resolver.resolve(merged)`. FeynMap now infers instance-attribute types from constructor assignments and annotations, and resolves `self.attribute.method()` only when exactly one target type is statically supported.

This is a generic Python capability, not a FeynMap-specific special case.

## Recursive improvement 2 — package re-exports

The next self-analysis gap came from FeynMap's own public adapter imports:

```python
from .adapters import PythonAdapter, HTMLAdapter, JavaScriptAdapter
```

Those public names are re-exported from deeper defining modules, including a two-hop framework path such as:

```text
feynmap.adapters.DjangoAdapter
    -> feynmap.adapters.frameworks.DjangoAdapter
    -> feynmap.adapters.frameworks.django.DjangoAdapter
```

FeynMap now builds a conservative package symbol-alias graph from static package imports and literal `__all__` declarations. It follows re-export chains transitively and creates a call/import edge only when the chain terminates at exactly one known semantic target. The full alias chain is retained in edge evidence.

This pass also repairs package-relative import edges that the original module-oriented relative-import resolver could misclassify inside `__init__.py` files.

## Recursive improvement 3 — share alias evidence with type resolution

FeynMap then exposed a boundary between its own semantic passes. `AdapterRegistry` is imported into `engine.py` through the public `feynmap.adapters` re-export surface, while instance dispatch such as:

```python
self.registry.detect_languages(...)
self.registry.detect_frameworks(...)
```

requires the attribute/type resolver to know the canonical class behind that public name.

The re-export pass now exposes its uniquely resolved alias index as reusable evidence. The instance-type resolver consumes that index when resolving annotations and constructor expressions. A grounded call edge retains the canonical type plus the exact alias chain used to reach it.

The golden benchmark now requires these FeynMap-on-FeynMap relationships:

```text
FeynMapEngine._select_languages
    CALLS -> AdapterRegistry.detect_languages
    CALLS -> AdapterRegistry.language

FeynMapEngine.analyze
    CALLS -> AdapterRegistry.detect_frameworks
    CALLS -> AdapterRegistry.framework
```

The ambiguity rule is unchanged: if an attribute can still denote multiple target types, no method edge is created.

## Remaining known blind spots

Current benchmark targets still include:

- explicit variable/state reads, writes and mutation,
- nested functions as first-class semantic nodes,
- dynamic dispatch, plugins and metaprogramming,
- parser-backed JavaScript/TypeScript semantics,
- build-system and CI execution topology.

These are important hardening areas, but none is required to begin repository snapshots or an MCP interface over already-evidenced facts.

## Quality gates

Phase 1.6 should establish release gates that do not require invented numeric thresholds:

1. all critical golden symbols are present,
2. all critical golden relationships are resolved,
3. graph validation has zero errors,
4. every critical resolved relationship has evidence,
5. ambiguous relationships remain unresolved rather than guessed,
6. previously accepted critical relationships never silently regress,
7. unresolved-call/evidence metrics are recorded so later snapshot diffs can detect deterioration.

Absolute numeric thresholds for unresolved-call counts or evidence percentages should be set only after an actually executed baseline report exists.
