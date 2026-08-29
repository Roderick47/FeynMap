# FeynMap

**A verifiable semantic map of software for humans and AI.**

FeynMap analyzes a repository programmatically, builds a machine-readable model of the system, records the evidence behind relationships, and exposes that model to developers and AI coding agents so they can reason about code with less guessing.

The long-term goal is language and framework independence. Python is the first native V3 language adapter. Django, Flask, and FastAPI are now independent framework adapters that enrich the generic Python graph after language analysis. The older V2 framework-aware analyzer remains available only as an explicit legacy path.

## Why FeynMap exists

AI coding agents are powerful, but large repositories force them to reconstruct architecture from partial context. That creates room for hallucinated files, dependencies, call paths, APIs, and change assumptions.

FeynMap changes the workflow:

```text
source repository
      ↓
deterministic language analysis
      ↓
canonical language graph + evidence
      ↓
optional framework enrichment
      ↓
query / impact / claim validation / migration planning
      ↓
human or AI reasoning
```

FeynMap distinguishes between facts that are directly evidenced, relationships that are supported by analysis, inferences, and things that are simply unknown.

## Core principles

1. **Programmatic truth first.** ASTs, symbols, imports, calls, data flow, framework metadata, tests, runtime traces, and repository history should ground the graph wherever possible.
2. **Evidence travels with every fact.** Nodes and edges can carry provenance, source locations, detector identity, confidence, and evidence type.
3. **Unknown is not false.** If FeynMap has no evidence for a relationship, the API reports it as unsupported/unknown rather than pretending the relationship cannot exist.
4. **Language-independent core.** Python, TypeScript, Rust, Java, C/C++, C#, Go, and future languages should map into the same ontology through adapters.
5. **Frameworks enrich languages.** Django, FastAPI, Rails, Spring, NestJS, and similar frameworks add semantics on top of language facts instead of duplicating parsers.
6. **Physics notation is a view, not the data model.** The Feynman-inspired representation remains useful, but the canonical graph is conventional and reusable by other tools.
7. **AI consumes the map; AI does not define truth.** AI inference can enrich the model, but it is explicitly labeled and should not silently overwrite programmatic evidence.

## Architecture

```text
                    Language adapters
          ┌────────────┬────────────┬────────────┐
          │ Python     │ TypeScript │ Rust ...   │
          └──────┬─────┴──────┬─────┴──────┬─────┘
                 │            │            │
                 └────────────┼────────────┘
                              ▼
                    Canonical Language Graph
                              │
                              ▼
                    Framework adapters
          ┌────────────┬────────────┬────────────┐
          │ Django     │ Flask      │ FastAPI... │
          └────────────┴────────────┴────────────┘
                              │
                              ▼
                    Canonical Semantic Graph
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
      Grounded Query      AI Grounding       Migration
          API               Service          Planning
```

See [`docs/ARCHITECTURE_V3.md`](docs/ARCHITECTURE_V3.md) for the detailed design.

## Current capabilities

### V3 semantic engine

The V3 `PythonAdapter` is framework-neutral and uses Python's standard-library AST directly. It currently emits:

- Python modules
- classes, functions, and methods
- lexical containment
- local and external imports
- project-local call relationships
- inheritance relationships
- decorators, parameters, and return annotations as Python attributes
- async/await relationships when the awaited call can be resolved
- explicit evidence and source locations
- unresolved-call metadata rather than fabricated edges

Framework meaning is added afterward by independent adapters:

- `DjangoAdapter`: Django models, views/DRF handlers, serializers, middleware
- `FlaskAdapter`: routes, Flask-SQLAlchemy models, Marshmallow schemas
- `FastAPIAdapter`: route handlers, SQLModel models, Pydantic schemas

Use `--framework none` to inspect only the raw Python language graph.

### Grounded reasoning and migration foundations

V3 also provides:

- canonical language-neutral node and edge types
- provenance/evidence objects
- confidence tiers: `verified`, `supported`, `inferred`, `unknown`
- independent language/framework adapter registry
- grounded dependency/caller/impact queries
- relationship claim validation for AI fact-checking
- AI context bundles
- migration-readiness assessment
- bounded migration units, initially aimed at future Rust migration

### V2 legacy pipeline

The original framework-aware Python analyzer remains available for compatibility and still includes:

- Django, Flask, FastAPI, and generic Python analysis
- recursive interaction tracing
- semantic clustering
- change-impact analysis
- reachability/dead-code analysis
- physics-inspired notation

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

For backwards-friendly usage, this also works:

```bash
feynmap .
```

The default output is `feynmap.semantic.json`.

Framework enrichment is auto-detected by default. To request one explicitly or disable it:

```bash
feynmap analyze . --framework django
feynmap analyze . --framework fastapi
feynmap analyze . --framework none
```

### Query a symbol

```bash
feynmap query . UserView --kind context --depth 2
feynmap query . process_payment --kind callers --depth 3
feynmap query . User --kind impact --depth 4
```

### Fact-check a claimed relationship

```bash
feynmap claim . PaymentView FraudDetector --relationship calls
```

If no matching edge exists, FeynMap reports that it currently has **no evidence** for the claim and returns nearby relationships. It does not claim impossibility.

### Plan a future Rust migration

```bash
feynmap migrate-plan . --to rust
```

This does **not** generate Rust yet. It measures evidence coverage, graph confidence, unknown regions, and partitions the repository into bounded migration units that can later feed a conversion/verification engine.

### Run the old V2 output pipeline

```bash
feynmap legacy . --framework django
```

## Python API

```python
from feynmap import FeynMapEngine, FeynMapQuery

engine = FeynMapEngine()
graph = engine.analyze(".", framework="auto")

query = FeynMapQuery(graph)
print(query.context_bundle("UserView", depth=2))
print(query.validate_claim("UserView", "User", "uses_data"))
```

For a framework-neutral Python graph:

```python
graph = engine.analyze(".", language="python", framework="none")
```

The old API remains lazily available:

```python
from feynmap import FeynExtractor, FeynNotator
```

## Direction

Phase 1—the separation of Python parsing from Django/Flask/FastAPI semantics—is complete. Phase 2 focuses on turning the semantic engine into an AI grounding service: persistent graph snapshots, incremental updates, MCP tools, and token-budgeted context retrieval.

Planned language adapters include TypeScript/JavaScript, Rust, Java, C/C++, C#, and Go. Planned evidence sources include runtime traces, tests/coverage, git/history coupling, dependency manifests, and type-checker/compiler facts.

Planned consumers include MCP tools for AI coding agents, IDE integration, code review and change-impact tools, architecture documentation, refactoring assistance, migration engines, Python/TypeScript/C++ → Rust conversion, and behavior verification after automated rewrites.

See [`ROADMAP.md`](ROADMAP.md).

## Mission

> **FeynMap builds a verifiable machine-readable model of a software system so humans and AI can reason about code without guessing.**

## License

MIT.
