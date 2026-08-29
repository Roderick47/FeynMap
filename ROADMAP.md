# FeynMap Roadmap

## Phase 0 — V3 foundation

- [x] Canonical language-neutral semantic graph
- [x] Evidence/provenance model
- [x] Confidence tiers
- [x] Adapter interfaces and registry
- [x] Initial Python V2 compatibility bridge
- [x] Grounded query API
- [x] Claim validation
- [x] Migration-readiness model
- [x] Migration-unit partitioning
- [x] Modern package/CLI structure

## Phase 1 — Separate Python from frameworks ✅

- [x] Replace the V3 Python/V2 bridge with a framework-neutral Python AST adapter
- [x] Extract Python modules, classes, functions, methods, imports, calls, inheritance, annotations, and async/await facts without framework knowledge
- [x] Add a first-class module/import graph
- [x] Move Django classification into `DjangoAdapter`
- [x] Move Flask classification into `FlaskAdapter`
- [x] Move FastAPI classification into `FastAPIAdapter`
- [x] Auto-detect framework adapters independently of language detection
- [x] Support framework-free analysis with `--framework none`
- [x] Preserve the V2 framework-aware pipeline only as an explicit legacy compatibility path
- [x] Add regression tests proving generic Python facts exist before framework enrichment

### Python semantic hardening backlog

These improve Python depth but are no longer architectural blockers.

- [ ] explicit variable/state read, write, and mutation edges
- [ ] richer type-resolution and inferred type constraints
- [ ] package/dependency manifest normalization
- [ ] dynamic dispatch confidence
- [ ] decorator/metaclass/plugin semantics beyond framework adapters

## Phase 1.5 — Repository orchestration & integration resolution ✅

FeynMap now treats a repository as a heterogeneous software system rather than choosing one dominant language.

- [x] Detect and run every applicable language adapter in one repository scan
- [x] Merge language graphs under one repository root while preserving node identity/evidence
- [x] Apply multiple framework adapters independently where applicable
- [x] Add framework-neutral HTML analysis
- [x] Add initial framework-neutral JavaScript analysis
- [x] Map multiple JavaScript functions/classes/methods and local calls
- [x] Resolve Python/framework template rendering → HTML
- [x] Resolve HTML script loading → JavaScript modules
- [x] Resolve HTML event handlers → JavaScript functions
- [x] Resolve JavaScript HTTP requests → Python framework endpoints
- [x] Add framework-neutral Python HTTP/process/file/database/FFI boundary extraction
- [x] Add JavaScript WebSocket/process/file/Electron/deep-link/native-bridge boundary extraction
- [x] Add a language-neutral integration-contract model
- [x] Resolve non-web channels: subprocess/CLI, queues, files, FFI, IPC, databases, sockets, deep links/app routes
- [x] Preserve unresolved/ambiguous boundaries instead of guessing
- [x] Track integration resolution at individual-contract granularity
- [x] Add mixed-language and non-web regression tests

### Integration hardening backlog

- [ ] embedded-language regions (inline `<script>`, Vue/Svelte single-file components, templated JS/CSS)
- [ ] richer JavaScript parsing via Tree-sitter/TypeScript compiler APIs
- [ ] route-prefix composition (`include_router`, nested routers, mounted apps, reverse routing)
- [ ] CSS/assets and bundler-generated dependency graphs
- [ ] protocol schemas (OpenAPI, protobuf/gRPC, GraphQL schemas)
- [ ] container/process topology from Docker/Compose/Kubernetes
- [ ] build-system orchestration (Make, Gradle, Cargo build scripts, npm scripts, CI workflows)

## Phase 1.6 — Recursive self-analysis / dogfooding 🚧

FeynMap is its own first serious benchmark. The objective is not merely to prove that self-analysis runs; it is to measure whether the graph captures FeynMap's known architecture and to turn every miss into an explicit improvement target.

- [x] Preserve the Phase 0–1.5 merge as baseline commit `4c378e3155b713b2b25bdb1c900c15244b213dad`
- [x] Create the `phase-1.6-self-hosting` development branch
- [x] Add a checked-in golden FeynMap architecture specification
- [x] Add `SelfAnalysisBenchmark` metrics for graph size, languages, evidence, unresolved calls, orphan nodes, and integration coverage
- [x] Add architecture symbol/relationship scoring
- [x] Add `feynmap self-check` CLI command
- [x] Add a regression test that runs `FeynMapEngine` on the FeynMap repository itself
- [ ] Record the first executed self-analysis baseline report
- [ ] Classify every missing critical relationship by root cause
- [ ] Improve the Python resolver using the baseline findings without weakening uncertainty handling
- [ ] Re-run the self-analysis and record semantic-quality deltas
- [ ] Establish minimum self-hosting quality gates for future releases

### Self-hosting quality targets

The first benchmark tracks these as measurements rather than pretending all are solved:

- critical architecture symbol recall
- critical architecture relationship recall
- unresolved Python call count
- nodes containing unresolved calls
- evidence coverage
- graph validation errors/warnings
- integration resolved/unresolved counts
- orphan semantic nodes
- confidence-tier distribution

Improvements should reduce unknown/unresolved regions while preserving the rule that ambiguous relationships remain unresolved rather than guessed.

## Phase 2 — AI grounding service

Phase 2 begins after the self-hosting baseline has exposed the most important semantic gaps.

- [ ] Persistent graph cache with incremental updates
- [ ] Repository snapshot/hash identity
- [ ] Semantic graph diffing between repository snapshots
- [ ] MCP server
- [ ] `get_symbol`, `find_callers`, `find_dependencies`, `trace_path`, `find_integrations`
- [ ] `validate_claim`, `change_impact`, `explain_evidence`, `unresolved`
- [ ] token-budgeted context bundles

## Phase 3 — More language adapters

Suggested order based on reuse and migration value:

1. TypeScript
2. Rust
3. Java
4. C / C++
5. C#
6. Go
7. Swift / Kotlin for native/mobile application graphs
8. Shell and build/config languages where they materially affect execution topology

JavaScript is now present as the first non-Python implementation and should later be upgraded with a parser-backed adapter. Framework adapters can then be added independently: Express/NestJS, Spring, ASP.NET, Axum/Actix, Android/iOS frameworks, etc.

## Phase 4 — Multi-source truth

- [ ] runtime trace ingestion
- [ ] test/coverage evidence
- [ ] git co-change evidence
- [ ] build/compiler/type-checker diagnostics
- [ ] dynamic dispatch confidence
- [ ] evidence conflict handling

## Phase 5 — Rust migration engine

- [ ] source type constraints
- [ ] mutation graph
- [ ] ownership/lifetime evidence
- [ ] side-effect and I/O boundaries
- [ ] async/concurrency boundaries
- [ ] dependency/crate mapping
- [ ] target architecture planner
- [ ] partial Python → Rust migration
- [ ] FastAPI/Flask service → Axum migration
- [ ] compile/test/behavior verification loop
- [ ] TypeScript/Node → Rust
- [ ] C/C++ → Rust

## Phase 6 — Ecosystem

- [ ] stable adapter SDK
- [ ] plugin discovery
- [ ] versioned ontology extensions
- [ ] IDE integrations
- [ ] CI/change-review integration
- [ ] graph storage backends for very large repositories
