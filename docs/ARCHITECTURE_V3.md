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

## Language adapters

A language adapter detects whether it can analyze a repository and emits language-level facts. The current Python adapter bridges the mature FeynMap V2 extractor into the V3 graph so the architecture can change without discarding tested Python logic.

Future adapters may use tree-sitter, compiler APIs, language servers, native AST tooling, or other deterministic sources.

## Framework adapters

Framework semantics belong above language parsing. For example, Python classes/functions/calls are language facts; Django models/routes/ORM semantics are framework enrichment.

The V2 bridge still resolves Django/Flask/FastAPI inside the legacy extractor. The next major refactor is to move those rules into independent `FrameworkAdapter` implementations.

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
