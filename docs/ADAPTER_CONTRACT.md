# Adapter Contract

## Language adapters

Implement `LanguageAdapter` from `feynmap.adapters.base`.

A language adapter must:

1. detect whether it can analyze a repository,
2. parse without executing untrusted project code whenever possible,
3. emit canonical `SemanticNode` and `SemanticEdge` objects,
4. attach source evidence and confidence,
5. preserve language-specific details in `attributes`,
6. report uncertainty instead of manufacturing relationships.

A language adapter **must not classify framework roles**. Python should emit a class as a Python class, not a Django model; TypeScript should emit a function as a TypeScript function, not an Express route. Framework meaning is a separate enrichment step.

The current `PythonAdapter` is the reference implementation. It uses the standard-library AST and emits modules, classes, functions, methods, containment, imports, calls, inheritance, annotations, and await relationships without importing Django, Flask, or FastAPI.

## Framework adapters

Implement `FrameworkAdapter`.

A framework adapter consumes an already-built language graph and enriches it. It may identify routes, models, serializers, dependency injection, ORM behavior, middleware, lifecycle hooks, templates, queues, or other framework-level concepts.

Framework adapters should:

1. declare the language they enrich,
2. detect themselves independently of language detection,
3. preserve existing language facts,
4. reclassify or annotate nodes only when framework evidence supports the role,
5. add evidence with `EvidenceKind.FRAMEWORK`,
6. never become a second parser for language syntax that the language adapter already owns.

Built-in Python framework adapters currently include `DjangoAdapter`, `FlaskAdapter`, and `FastAPIAdapter` under `feynmap/adapters/frameworks/`.

## Engine order

The engine always follows this order:

```text
repository
  ↓
language detection
  ↓
language adapter
  ↓
canonical language graph
  ↓
framework detection
  ↓
framework adapter enrichment
  ↓
final semantic graph
```

`--framework none` skips framework enrichment entirely and exposes the raw language graph.

## Evidence rule

Adapters should prefer this hierarchy:

1. compiler/parser/type-checker fact,
2. framework configuration fact,
3. test/runtime observation,
4. repository-history evidence,
5. deterministic heuristic,
6. AI inference.

AI inference must always be labeled `ai_inference` and must not silently replace stronger evidence.

## IDs

Node IDs must be stable within a repository and, where possible, include module/file scope to avoid collisions. Edge IDs must be deterministic for the same observed relationship.

## No execution by default

Static adapters should not import or execute analyzed application code by default. Runtime evidence must be opt-in and clearly identified.
