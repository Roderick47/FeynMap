# FeynMap

**A verifiable semantic map of software for humans and AI.**

FeynMap analyzes a repository programmatically, builds a machine-readable model of the system, records the evidence behind relationships, and exposes that model to developers and AI coding agents so they can reason about code with less guessing.

FeynMap now treats a repository as a **heterogeneous software system** rather than selecting one dominant language. Python, HTML, JavaScript, frameworks, routes, templates, HTTP calls, subprocesses, files, IPC and other runtime boundaries can coexist in one unified semantic graph.

## Why FeynMap exists

AI coding agents are powerful, but large repositories force them to reconstruct architecture from partial context. That creates room for hallucinated files, dependencies, call paths, APIs and change assumptions.

FeynMap changes the workflow:

```text
source repository
      ↓
detect all applicable languages
      ↓
deterministic language analysis
      ↓
framework enrichment
      ↓
merge language graphs
      ↓
cross-language / cross-runtime resolution
      ↓
canonical semantic graph + evidence
      ↓
query / impact / claim validation / migration planning
      ↓
human or AI reasoning
```

FeynMap distinguishes between facts that are directly evidenced, relationships that are supported by analysis, inferences, and things that are simply unknown.

## Core principles

1. **Programmatic truth first.** ASTs, parsers, symbols, imports, calls, framework metadata, integration boundaries, tests, runtime traces and repository history should ground the graph wherever possible.
2. **Evidence travels with every fact.** Nodes and edges can carry provenance, source locations, detector identity, confidence and evidence type.
3. **Unknown is not false.** If FeynMap has no evidence for a relationship, it reports it as unsupported/unresolved rather than pretending the relationship cannot exist.
4. **Language-independent core.** Python, HTML, JavaScript, TypeScript, Rust, Java, C/C++, C#, Go, Swift, Kotlin and future languages should map into the same ontology through adapters.
5. **Frameworks enrich languages.** Django, Flask, FastAPI, Spring, NestJS, Axum and similar frameworks add semantics on top of language facts instead of duplicating parsers.
6. **Cross-language edges are protocol-oriented.** FeynMap resolves `http_client` to `http_server`, `process_spawn` to `cli_entrypoint`, `ffi_import` to `ffi_export`, etc., rather than hard-coding language pairs.
7. **Physics notation is a view, not the data model.** The Feynman-inspired representation remains useful, but the canonical graph is conventional and reusable by other tools.
8. **AI consumes the map; AI does not define truth.** AI inference can enrich the model, but it is explicitly labeled and should not silently overwrite programmatic evidence.

## Architecture

```text
                          Repository
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
     PythonAdapter       HTMLAdapter      JavaScriptAdapter
          │                   │                   │
          ▼                   ▼                   ▼
    Python graph          HTML graph          JS graph
          │                                       │
          ▼                                       │
 Django / Flask /                              future
 FastAPI adapters                              frameworks
          │                                       │
          └───────────────────┬───────────────────┘
                              ▼
                    Unified Repository Graph
                              │
                              ▼
                    Integration Resolver
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  Grounded Query        AI Grounding          Migration
       API                 Service             Planning
```

See [`docs/ARCHITECTURE_V3.md`](docs/ARCHITECTURE_V3.md) and [`docs/MULTILANGUAGE_ORCHESTRATION.md`](docs/MULTILANGUAGE_ORCHESTRATION.md).

## Current capabilities

### Repository-level multi-language analysis

With `language=auto`, FeynMap runs every registered language adapter that recognizes the repository and merges the results beneath one repository node.

Current V3 language adapters:

- **Python** — modules, classes, functions, methods, imports, project-local calls, inheritance, annotations, async/await and unresolved-call metadata.
- **HTML** — documents/templates, script loads, DOM event handlers, forms, HTMX requests and internal navigation targets.
- **JavaScript** — modules, functions, arrow functions, classes, methods, imports, local calls, inheritance plus selected runtime boundaries.

The first JavaScript adapter is dependency-free and deterministic. It is intentionally a foundation that can later be replaced/enriched with Tree-sitter or TypeScript compiler APIs without changing the semantic graph contract.

### Framework enrichment

Python framework meaning is added after language analysis:

- `DjangoAdapter`: models, views/DRF handlers, serializers, middleware, URL route contracts and rendered templates.
- `FlaskAdapter`: routes, Flask-SQLAlchemy models, Marshmallow schemas, route contracts and rendered templates.
- `FastAPIAdapter`: route handlers, SQLModel models, Pydantic schemas, HTTP/WebSocket route contracts and templates.

Multiple framework adapters can coexist in one repository when independently detected.

### Cross-language and cross-runtime resolution

The resolver currently understands contracts for:

- HTTP client ↔ server
- WebSocket client ↔ server
- RPC client ↔ server
- queue publish ↔ subscribe
- subprocess spawn ↔ CLI entrypoint
- FFI/native import ↔ export
- IPC send ↔ receive
- database client ↔ server
- socket client ↔ server
- deep link ↔ app route
- file write ↔ read
- backend template render ↔ HTML document
- HTML script load ↔ JavaScript module
- HTML event handler ↔ JavaScript function

Example:

```text
Python home()
    ↓ renders
index.html
    ↓ loads
app.js
    ↓ contains
loadItems()
    ↓ GET /api/items
Python items()
```

The same model works outside web development. JavaScript/Python currently emit selected process, file, HTTP, database, FFI, Electron IPC, deep-link and native/mobile bridge contracts. Future Swift/Kotlin/Rust/Java/C++ adapters can meet the same contracts without changing the resolver architecture.

### Grounded reasoning and migration foundations

V3 also provides:

- canonical language-neutral node and edge types
- provenance/evidence objects
- confidence tiers: `verified`, `supported`, `inferred`, `unknown`
- independent language/framework adapter registry
- integration-resolution evidence
- unresolved integration-contract reporting
- grounded dependency/caller/impact queries
- relationship claim validation for AI fact-checking
- AI context bundles
- migration-readiness assessment
- bounded migration units, initially aimed at future Rust migration

### V2 legacy pipeline

The original framework-aware Python analyzer remains available for compatibility and still includes recursive interaction tracing, semantic clustering, change-impact analysis, reachability/dead-code analysis and physics-inspired notation.

V3 no longer depends on this parser for normal `analyze`, `query`, `claim`, or `migrate-plan` commands.

## Install

```bash
pip install -e .
```

FeynMap keeps the core dependency-free for now.

## CLI

### Analyze a repository

```bash
feynmap analyze .
```

`auto` now means **all positively detected language adapters**, not “pick the best language.”

You can constrain languages explicitly:

```bash
feynmap analyze . --language python
feynmap analyze . --language python,javascript
```

Framework enrichment is auto-detected by default. To request one explicitly or disable it:

```bash
feynmap analyze . --framework django
feynmap analyze . --framework fastapi
feynmap analyze . --framework none
```

The default output is `feynmap.semantic.json`.

### Query a symbol

```bash
feynmap query . UserView --kind context --depth 2
feynmap query . loadItems --kind callers --depth 3
feynmap query . User --kind impact --depth 4
```

### Fact-check a claimed relationship

```bash
feynmap claim . loadItems items --relationship requests
```

If no matching edge exists, FeynMap reports that it currently has **no evidence** for the claim. It does not claim impossibility.

### Plan a future Rust migration

```bash
feynmap migrate-plan . --to rust
```

This does **not** generate Rust yet. It measures evidence coverage, graph confidence, unknown regions and partitions the repository into bounded migration units.

### Run the old V2 output pipeline

```bash
feynmap legacy . --framework django
```

## Python API

```python
from feynmap import FeynMapEngine, FeynMapQuery

engine = FeynMapEngine()
graph = engine.analyze(".")

print(graph.metadata["language_names"])
print(graph.metadata["integration"])

query = FeynMapQuery(graph)
print(query.context_bundle("loadItems", depth=3))
```

For framework-neutral Python only:

```python
graph = engine.analyze(".", language="python", framework="none")
```

The old API remains lazily available:

```python
from feynmap import FeynExtractor, FeynNotator
```

## Direction

Phase 1 (framework-neutral Python) and Phase 1.5 (repository multi-language orchestration and cross-runtime resolution) are now implemented on the V3 refactor branch.

The next major phase is the AI grounding service: persistent graph snapshots, incremental updates, repository identity, MCP tools and token-budgeted context retrieval.

Before broad production use, the integration layer still needs hardening for embedded languages, richer JavaScript/TypeScript parsing, composed/nested routes, protocol schemas, build/container topology and additional native/mobile adapters. See [`ROADMAP.md`](ROADMAP.md).

## Mission

> **FeynMap builds a verifiable machine-readable model of a software system so humans and AI can reason about code without guessing.**

## License

MIT.
