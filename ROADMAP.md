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

These improve Python depth but are no longer prerequisites for Phase 2 because the architectural separation is complete.

- [ ] explicit variable/state read, write, and mutation edges
- [ ] richer type-resolution and inferred type constraints
- [ ] package/dependency manifest normalization
- [ ] dynamic dispatch confidence
- [ ] decorator/metaclass/plugin semantics beyond framework adapters

## Phase 2 — AI grounding service

- [ ] Persistent graph cache with incremental updates
- [ ] Repository snapshot/hash identity
- [ ] MCP server
- [ ] `get_symbol`, `find_callers`, `find_dependencies`, `trace_path`
- [ ] `validate_claim`, `change_impact`
- [ ] token-budgeted context bundles

## Phase 3 — More languages

Suggested order based on reuse and migration value:

1. TypeScript / JavaScript
2. Rust
3. Java
4. C / C++
5. C#
6. Go

Framework adapters can then be added independently: Express/NestJS, Spring, ASP.NET, etc.

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
