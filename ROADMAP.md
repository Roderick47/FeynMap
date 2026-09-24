# FeynMap Roadmap

## 2026 realignment — sparse knowledge activation substrate

The completed semantic-graph, evidence, snapshot, context, and JEV work remains
the foundation. The product priority is now a **low-latency sparse
knowledge-activation substrate** rather than treating MCP or a grounding server
as the end state.

MCP, HTTP, IDE, and agent integrations become thin consumers of the substrate.
The hot path should minimize graph regions touched, nodes activated, context
tokens delivered, and routing latency while preserving task quality.

See `docs/SPARSE_KNOWLEDGE_SUBSTRATE.md` for the architecture and definitions.

### S0 — Measure the current activation path 🚧

- [x] Evidence-backed canonical graph
- [x] Immutable snapshots and token-budgeted context
- [x] Provider-neutral JEV judgment layer
- [x] JEV-guided bounded node/concept search (PR #28)
- [x] Candidate-touch and knowledge-activation metrics
- [ ] Baseline the metrics on FeynMap itself
- [ ] Baseline the metrics on a substantially larger real repository
- [ ] Add routing-latency and context-token instrumentation

### S1 — Region-first sparse routing

- [ ] Stable region/cluster summaries over the canonical graph
- [ ] Route to regions before individual nodes
- [ ] Reuse region selections within one task
- [ ] Compare flat vs region-first recall, activation ratio, and latency
- [ ] Preserve deterministic routing when JEV is unavailable

### S2 — Adaptive sufficiency and effort

- [ ] Provider-neutral sufficiency contract
- [ ] Marginal information-gain tracking
- [ ] Confidence/coverage-based early stopping
- [ ] Escalation policy: deterministic → JEV → optional LLM
- [ ] Fast/normal/deep budgets driven by uncertainty rather than fixed user mode

### S3 — Minimal sufficient context

- [ ] Explicit post-activation context-selection stage
- [ ] Evidence-preserving endpoint/relationship packing
- [ ] Quality-retention benchmark against full context and baseline retrieval
- [ ] Context-compression and downstream-cost metrics

### S4 — Active state for long-horizon agents

- [ ] Distinguish persistent graph memory from active working context
- [ ] Reuse task regions across tool calls
- [ ] Re-expand or invalidate state when new evidence changes the task
- [ ] Measure context growth avoided over long agent runs

### S5 — Tool-space routing

- [ ] Represent tool capabilities as routable grounded contracts
- [ ] Expose only the small relevant tool subset to the downstream model
- [ ] Measure tool-schema token reduction and routing quality

### S6 — Performance implementation

- [ ] Profile the Python hot path before porting
- [ ] Cache only measured bottlenecks
- [ ] Freeze substrate contracts
- [ ] Port latency-critical pieces to Rust where profiling justifies it

The older phases below remain valid capability work. Their priority is now
judged by how much they improve graph truth, activation quality, context
efficiency, or delivery of the substrate.

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
- [ ] shared Tree-sitter parsing/source-region foundation with explicit parser provenance and deterministic node identities
- [ ] parser-backed JavaScript and TypeScript via Tree-sitter, with conformance comparisons against the dependency-free JavaScript adapter
- [ ] optional TypeScript compiler enrichment for type/module facts that Tree-sitter syntax alone cannot prove
- [ ] route-prefix composition (`include_router`, nested routers, mounted apps, reverse routing)
- [ ] CSS/assets and bundler-generated dependency graphs
- [ ] protocol schemas (OpenAPI, protobuf/gRPC, GraphQL schemas)
- [ ] container/process topology from Docker/Compose/Kubernetes
- [ ] build-system orchestration (Make, Gradle, Cargo build scripts, npm scripts, CI workflows)

## Phase 1.6 — Recursive self-analysis / dogfooding ✅

FeynMap is its own first serious benchmark. The architectural self-hosting foundation is complete and merged; numeric baseline execution remains externally blocked by the GitHub Actions runner condition.

- [x] Preserve the Phase 0–1.5 merge as baseline commit `4c378e3155b713b2b25bdb1c900c15244b213dad`
- [x] Add a checked-in golden FeynMap architecture specification
- [x] Add `SelfAnalysisBenchmark` metrics for graph size, languages, evidence, unresolved calls, orphan nodes, and integration coverage
- [x] Add architecture symbol/relationship scoring
- [x] Add `feynmap self-check` CLI command
- [x] Add a regression test that runs `FeynMapEngine` on the FeynMap repository itself
- [x] Recursive improvement 1: resolve `self.attribute.method()` from unique constructor/type evidence
- [x] Recursive improvement 2: resolve transitive Python package re-exports conservatively
- [x] Repair package-relative import edges discovered while analyzing FeynMap's own `__init__.py` surfaces
- [x] Recursive improvement 3: reuse package re-export evidence in annotation/instance-type resolution
- [x] Require FeynMap's own `self.registry.*` dispatch relationships in the golden benchmark
- [x] Establish invariant self-hosting quality gates: golden symbols, critical relationships, graph validity, and critical-edge evidence
- [ ] Record the first actually executed self-analysis baseline report when an execution environment is available
- [ ] Record before/after numeric semantic-quality deltas once snapshots can be executed and compared

### Self-hosting quality gates

- [x] all golden architecture symbols must be present
- [x] all critical golden architecture relationships must be resolved
- [x] semantic graph validation must have zero errors
- [x] every resolved critical golden relationship must carry evidence
- [x] ambiguity regression tests preserve the rule that multiple candidate targets remain unresolved

The benchmark continues to record unresolved-call count, evidence coverage, orphan nodes and integration resolution counts. Absolute thresholds for those metrics are deferred until the first actually executed baseline report exists.

### Remaining self-hosting hardening

These remain useful improvements but do not block stored-graph/MCP work over already-evidenced facts:

- explicit variable/state reads, writes and mutations
- nested functions as first-class nodes
- dynamic dispatch, plugin and metaprogramming semantics
- parser-backed JavaScript/TypeScript
- build-system and CI execution topology

## Phase 2 — AI grounding service 🚧

Phase 2 starts with persistent repository identity so coding agents do not force a full reparse on every request.

### Phase 2A — Repository snapshots and persistence ✅

The Phase 2A foundation is complete. True changed-file fragment reuse remains a performance optimization, not a correctness or MCP blocker.

- [x] Semantic graph deserialization with schema/version checks and diagnostic preservation
- [x] Repository locator and snapshot/hash identity
- [x] Sanitized Git-origin identity where available
- [x] File/content SHA-256 inventory
- [x] Immutable SQLite snapshot store
- [x] Per-repository current snapshot pointer
- [x] Stored graph hash verification on load
- [x] Exclude `.feynmap` state from repository content identity
- [x] Add `feynmap snapshot` analyze-once-and-persist workflow
- [x] Normalize repository-root semantic identity for clone-independent graph/snapshot hashes
- [x] File-inventory diff between repository snapshots
- [x] Semantic graph diffing between repository snapshots
- [x] Add `feynmap diff` stored-snapshot workflow without reparsing historical states
- [x] Conservative incremental planning driven by changed-file inventory and dependency closure
- [x] Zero-analysis reuse for unchanged repositories with repository/options/analysis-contract guards
- [x] Full-rebuild fallback whenever changed-fragment equivalence cannot yet be proven
- [x] Token-budgeted context primitives over a stored snapshot
- [x] Add `feynmap incremental` and `feynmap stored-query` workflows

#### Phase 2A optimization backlog

- [ ] True changed-file semantic fragment reuse with adapter-level partial parse/merge conformance

See `docs/SNAPSHOTS.md` for the snapshot identity/persistence contract and `docs/INCREMENTAL_CONTEXT.md` for incremental/context safety semantics.

### Phase 2B — MCP grounding service 🚧

Groundwork has started, but no MCP SDK/transport or remote hosting dependency has been introduced yet.

- [x] Transport-neutral repository/snapshot-aware `GroundingService`
- [x] Versioned read-only grounding tool catalog with JSON Schema 2020-12 inputs
- [x] Service-layer `get_symbol`, `find_callers`, `find_dependencies`, `trace_path`, `find_integrations`
- [x] Service-layer `validate_claim`, `change_impact`, `explain_evidence`, `unresolved`
- [x] Service-layer `semantic_diff`, repository summary, and token-budgeted `context_bundle`
- [x] Keep MCP/application contracts independent of Python server internals for future Rust compatibility
- [ ] Decide MCP runtime packaging: raise Python floor to 3.10+, optional 3.10+ MCP component, or another split
- [ ] Register the grounding catalog with the official MCP SDK
- [ ] Local stdio MCP server transport and protocol/conformance tests
- [ ] Remote Streamable HTTP transport
- [ ] Remote authentication/authorization and tenant/repository access controls
- [ ] Production hosting/shared-storage deployment

See `docs/MCP_GROUNDING.md` for the tool boundary, transport plan, hosting choices and the project-owner decisions required before remote deployment.

### Phase 2C — AI-assisted real-world validation 🚧

Real-world testing expands through explicit evidence gates rather than a single
"production ready" switch. See `docs/AI_REAL_WORLD_VALIDATION.md` for the full
checkpoint definitions, safety boundaries, measurements, and rollback rules.

- [x] R0 manual read-only grounding trials are possible with current CLI/snapshot outputs
- [x] Freeze non-destructive dual-channel context/repair guidance through v1R
- [x] Build a provider-neutral held-out-capable repair benchmark harness and immutable run manifests
- [x] Add independent failing development fixtures and oracle-leakage guards for harness validation
- [x] Add outcome scoring and four-arm comparison with completeness diagnostics
- [x] Add disposable local execution, sealed verifier files, bounded test commands, and deterministic patch hashing
- [x] Add an explicit argv/JSON command-agent protocol with opt-in environment forwarding
- [ ] Compare unassisted, deterministic-context, relevance-context, and dual-channel AI repair arms
- [ ] Record patch correctness, tests, changed files, unsupported claims, searches, time, and token cost
- [ ] R1 controlled AI repair trial on disposable worktrees with new non-Wikonomi tasks
- [ ] R2 local read-only stdio MCP alpha for real feature-branch usage
- [ ] Capture privacy-preserving local MCP usefulness and outcome feedback
- [ ] R3 Tree-sitter JavaScript/TypeScript mixed-language alpha after conformance gates
- [ ] R4 selected-team beta with CI plus test/runtime/history evidence
- [ ] R5 authenticated remote pilot with repository-scoped authorization

The first normal integrated AI usage begins at **R2 local MCP alpha**. R0 can be
tested manually now; R1 is the first controlled AI repair checkpoint.

See `docs/AI_REPAIR_BENCHMARK.md` for the R1 schemas, commands, development
fixtures, and remaining execution-adapter/held-out-corpus gates.

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

This phase is about FeynMap helping migrate *other software* into Rust. It is separate from the later Rust-native implementation of FeynMap itself.

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

## Phase 7 — Rust-native FeynMap implementation

After the Python/reference architecture, snapshot model, query API, MCP surface, and adapter contracts are stable, implement FeynMap itself in Rust for lower latency, stronger concurrency, and efficient API/MCP deployment.

The Rust implementation should be a compatible implementation of the same contracts rather than a separate product.

- [ ] Freeze/version the semantic graph, evidence, snapshot, diff, and MCP contracts for cross-runtime compatibility
- [ ] Add Python ↔ Rust conformance fixtures: identical inputs must produce contract-compatible semantic outputs
- [ ] Port the language-neutral ontology and semantic graph core to Rust
- [ ] Port repository identity, hashing, snapshot persistence, and semantic diffing to Rust
- [ ] Port grounded query/claim/impact/context services to Rust
- [ ] Implement the MCP server and API service natively in Rust
- [ ] Port or replace language adapters with Rust/parser-backed implementations where performance justifies it
- [ ] Preserve compatibility with snapshots produced by the Python reference implementation
- [ ] Benchmark latency, throughput, memory use, startup time, and incremental-analysis performance against the Python implementation
- [ ] Keep Python bindings/client libraries where they are useful without making the Rust service depend on Python at runtime
