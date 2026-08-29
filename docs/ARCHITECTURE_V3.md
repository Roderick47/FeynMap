# FeynMap V3 Architecture

## Goal

FeynMap V3 turns the project from a Python-framework analyzer into a reusable semantic infrastructure layer for software engineering and AI agents.

The architecture separates five concerns that were previously mixed together:

1. source-language parsing,
2. framework interpretation,
3. canonical software semantics,
4. querying and reasoning,
5. downstream applications such as migration.

## Canonical semantic core

The canonical graph lives under `feynmap/core/` and must not import Django, Flask, FastAPI, Python AST machinery, or the physics notation.

Core nodes represent concepts such as modules, functions, classes, data models, handlers, services, transformers, UI surfaces, databases, queues, and external systems.

Core edges represent relationships such as calls, imports, containment, dependencies, reads/writes/mutations, data usage, serialization, validation, persistence, requests, events, ownership, and data/control flow.

Language-specific details remain in `attributes` unless they are useful across ecosystems.

## Evidence and confidence

Every semantic fact can carry evidence. Evidence kinds include static analysis, framework analysis, runtime traces, test observations, repository history, heuristics, and AI inference.

Each record identifies the detector, source location when known, detail, and confidence. AI-generated assertions must never be indistinguishable from parser-derived facts.

Confidence tiers are `verified`, `supported`, `inferred`, and `unknown`.

## Phase 1 architecture: language first, framework second

Phase 1 removes framework knowledge from the V3 Python extractor.

`PythonAdapter` now uses Python's AST directly and owns only Python semantics:

- modules,
- classes,
- functions and methods,
- lexical containment,
- imports,
- project-local call resolution,
- inheritance,
- decorators/annotations stored as Python attributes,
- async/await relationships,
- unresolved-call evidence where static resolution is insufficient.

It does **not** decide that a class is a Django model, a function is a Flask route, or a Pydantic class is a FastAPI schema.

The engine performs framework enrichment only after the language graph exists:

```text
repository
    ↓
PythonAdapter
    ↓
framework-neutral Python graph
    ↓
DjangoAdapter / FlaskAdapter / FastAPIAdapter
    ↓
framework-enriched semantic graph
```

This same contract is intended to support future combinations such as TypeScript + Express/NestJS, Java + Spring, C# + ASP.NET, and Rust + Axum/Actix without duplicating language parsers.

## Language adapters

A language adapter detects whether it can analyze a repository and emits language-level facts only.

The current Python adapter is a native V3 adapter backed by the standard-library AST. It no longer calls the V2 Django/Flask/FastAPI-aware extractor.

Future adapters may use tree-sitter, compiler APIs, language servers, native AST tooling, or other deterministic sources.

## Framework adapters

Framework semantics belong above language parsing. Python classes/functions/calls are language facts; Django models/views/serializers, Flask routes, and FastAPI endpoints/schemas are framework enrichment.

Built-in V3 framework adapters now live under `feynmap/adapters/frameworks/`:

- `DjangoAdapter`
- `FlaskAdapter`
- `FastAPIAdapter`

Framework detection is independent of language detection. `--framework auto` selects the strongest compatible framework adapter; `--framework none` intentionally exposes the raw language graph.

The old framework-aware V2 parser remains only behind the explicit `legacy` compatibility path.

## Query layer

`FeynMapQuery` is the first stable consumer interface for humans and AI. It supports symbol resolution, dependencies, callers, reverse impact traversal, AI context bundles, and claim validation.

Claim validation is conservative: a missing edge means FeynMap currently has no evidence for the relationship, not that the relationship is impossible.

## Migration layer

`MigrationPlanner` consumes the semantic graph; it is not part of parsing. The initial implementation measures graph grounding and creates bounded migration units.

A complete Rust migration pipeline should eventually be:

```text
semantic graph
    ↓
state + mutation + ownership analysis
    ↓
I/O and async boundary analysis
    ↓
migration units
    ↓
target architecture plan
    ↓
code generation
    ↓
compile/test
    ↓
behavior comparison
    ↓
repair loop
```

## Multi-source truth

Static analysis is necessary but not sufficient for highly dynamic systems. The canonical graph is designed to accept runtime call paths, tests/coverage, database/query traces, message flows, git co-change relationships, compiler/type-checker facts, and production telemetry.

These sources enrich rather than overwrite stronger evidence.

## AI integration

FeynMap should eventually expose MCP/server tools such as `get_symbol`, `find_callers`, `find_dependencies`, `trace_execution`, `change_impact`, `validate_claim`, `find_entrypoints`, `find_dead_code`, and `migration_plan`.

Every response should preserve evidence and confidence so an agent can reason about uncertainty.

## Physics notation

The Feynman-inspired model remains a visualization/interpretation layer, not the canonical schema:

```text
Canonical Semantic Graph
        ├── JSON
        ├── grounded query API
        ├── migration engine
        ├── MCP
        └── physics notation / diagrams
```
