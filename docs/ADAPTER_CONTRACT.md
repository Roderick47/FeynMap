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

A language adapter should not encode framework semantics that can be separated cleanly.

## Framework adapters

Implement `FrameworkAdapter`.

A framework adapter enriches an existing language graph. It may identify routes, models, serializers, dependency injection, ORM behavior, middleware, lifecycle hooks, templates, queues, or other framework-level concepts.

Framework adapters should add evidence with `EvidenceKind.FRAMEWORK`.

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
