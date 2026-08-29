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

## Golden architecture

`self_hosting/feynmap_golden.json` contains architecture facts that should be discoverable independently of the current analyzer implementation.

Examples include:

```text
FeynMapEngine.analyze
    CALLS -> merge_language_graphs

FeynMapEngine.analyze
    CALLS -> IntegrationResolver.resolve

default_registry
    CALLS -> PythonAdapter
    CALLS -> HTMLAdapter
    CALLS -> JavaScriptAdapter
    CALLS -> DjangoAdapter
    CALLS -> FlaskAdapter
    CALLS -> FastAPIAdapter
```

Some golden relationships are intentionally beyond today's resolver. A missing golden edge is therefore a measured semantic blind spot, not permission to fabricate an edge.

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

The aggregate score intentionally weights relationships more heavily than symbol presence. Discovering that `IntegrationResolver` exists is useful; discovering how `FeynMapEngine` reaches it is more important for architectural reasoning.

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

## First expected blind spot

The current generic Python resolver can resolve direct imported calls and `self.method()` calls when the target method belongs to the same statically known class. It does not yet infer the runtime type of attributes such as `self.resolver`.

Therefore this true architecture relationship is an important early benchmark target:

```text
FeynMapEngine.analyze
    CALLS -> IntegrationResolver.resolve
```

The source contains `self.resolver.resolve(merged)`, but proving the target requires connecting constructor assignment/type evidence to later attribute dispatch.

That gives Phase 1.6 a concrete first research task: improve attribute/type-aware Python call resolution without guessing dynamic dispatch.

## Quality gates

Phase 1.6 should eventually establish release gates such as:

1. all critical golden symbols are present,
2. all previously resolved critical golden relationships remain resolved,
3. graph validation has zero errors,
4. unresolved-call count does not regress without an explicit explanation,
5. evidence coverage does not regress materially,
6. ambiguous relationships remain labeled unresolved,
7. each newly resolved golden edge includes evidence and confidence.

The exact numeric thresholds will be set after the first executed baseline report rather than invented in advance.
