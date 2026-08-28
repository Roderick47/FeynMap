# FeynMap

**A verifiable semantic map of software for humans and AI.**

FeynMap analyzes a repository programmatically, builds a machine-readable model of the system, records the evidence behind relationships, and exposes that model to developers and AI coding agents so they can reason about code with less guessing.

The long-term goal is language and framework independence. Python is the first mature adapter; Django, Flask, FastAPI, and generic Python analysis are preserved from FeynMap V2 while the project moves toward a universal semantic core.

## Why FeynMap exists

AI coding agents are powerful, but large repositories force them to reconstruct architecture from partial context. That creates room for hallucinated files, dependencies, call paths, APIs, and change assumptions.

FeynMap changes the workflow:

```text
source repository
      ↓
deterministic language analysis
      ↓
framework semantics
      ↓
canonical semantic graph + evidence
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
5. **Frameworks enrich languages.** Django, FastAPI, Rails, Spring, NestJS, and similar frameworks should add semantics on top of language facts instead of duplicating parsers.
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
                    Canonical Semantic Graph
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
      Framework          Grounded Query      Migration
      enrichment             API             Planning
            │                 │                 │
            └─────────────────┼─────────────────┘
                              ▼
                  Humans / IDEs / AI agents
```

See [`docs/ARCHITECTURE_V3.md`](docs/ARCHITECTURE_V3.md) for the detailed design.

## Current capabilities

The existing V2 Python analyzer remains available and currently understands:

- Django
- Flask
- FastAPI
- generic Python
- scope-aware call relationships
- recursive interaction tracing
- semantic clustering
- change-impact analysis
- reachability/dead-code analysis
- physics-inspired notation

The V3 foundation adds:

- canonical language-neutral node and edge types
- provenance/evidence objects
- confidence tiers: `verified`, `supported`, `inferred`, `unknown`
- adapter registry
- Python V2 → semantic graph bridge
- grounded dependency/caller/impact queries
- relationship claim validation for AI fact-checking
- AI context bundles
- migration-readiness assessment
- bounded migration units, initially aimed at future Rust migration

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

The old API remains lazily available:

```python
from feynmap import FeynExtractor, FeynNotator
```

## Direction

FeynMap is becoming infrastructure rather than a framework-specific analyzer.

Planned adapters and evidence sources include TypeScript/JavaScript, Rust, Java, C/C++, C#, Go, runtime traces, tests/coverage, git/history coupling, build/dependency manifests, and type-checker/compiler facts.

Planned consumers include MCP tools for AI coding agents, IDE integration, code review and change-impact tools, architecture documentation, refactoring assistance, migration engines, Python/TypeScript/C++ → Rust conversion, and behavior verification after automated rewrites.

## Mission

> **FeynMap builds a verifiable machine-readable model of a software system so humans and AI can reason about code without guessing.**

## License

MIT.
