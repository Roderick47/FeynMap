# FeynMap Roadmap

## Phase 0 — V3 foundation

- [x] Canonical language-neutral semantic graph
- [x] Evidence/provenance model
- [x] Confidence tiers
- [x] Adapter interfaces and registry
- [x] Python V2 compatibility adapter
- [x] Grounded query API
- [x] Claim validation
- [x] Migration-readiness model
- [x] Migration-unit partitioning
- [x] Modern package/CLI structure

## Phase 1 — Separate Python from frameworks

- [ ] Extract pure Python symbols/imports/calls/types into Python adapter
- [ ] Move Django semantics into `DjangoAdapter`
- [ ] Move Flask semantics into `FlaskAdapter`
- [ ] Move FastAPI semantics into `FastAPIAdapter`
- [ ] Add first-class module/import graph
- [ ] Add explicit reads/writes/mutations
- [ ] Add async/await and concurrency facts
- [ ] Add package/dependency manifest analysis

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
