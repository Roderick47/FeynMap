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

Recursive development is now the default project discipline: substrate work stays on one authoritative integration line, FeynMap self-analyzes in CI, and manual-fallback misses become benchmark evidence. See `docs/RECURSIVE_DEVELOPMENT.md`.

### S0 — Measure the current activation path 🚧

- [x] Evidence-backed canonical graph
- [x] Immutable snapshots and token-budgeted context
- [x] Provider-neutral JEV judgment layer
- [x] JEV-guided bounded node/concept search (PR #28)
- [x] Candidate-touch and knowledge-activation metrics
- [x] Baseline the metrics on FeynMap itself
- [x] Baseline the metrics on a substantially larger real repository
- [x] Add routing-latency and context-token instrumentation

### S1 — Region-first sparse routing

- [x] Stable file/module region summaries over the canonical graph
- [x] Add a bounded global region route alongside local semantic traversal
- [x] Reuse one region selection within each task invocation
- [x] Compare flat vs region-hybrid recall, activation ratio, context, and latency
- [x] Preserve deterministic routing when JEV is unavailable


S1 benchmark outcome on the five pinned Wikonomi v1F tasks: flat deterministic
search retained 85% mean essential recall; the accepted local + region hybrid
reached 100% (5/5 full-recall tasks) while keeping mean knowledge activation at
about 1.3% of the graph. The hybrid currently costs more latency/context than
flat search, so S2 should make the global channel conditional on sufficiency
rather than always-on. Hard region filtering was tested and rejected because it
damaged recall.

### S2 — Adaptive sufficiency and effort

- [x] Provider-neutral sufficiency contract
- [x] Marginal information-gain tracking
- [x] Confidence/coverage-based early stopping
- [x] Escalation policy: deterministic → region → judgment provider (JEV / optional expensive provider)
- [x] Fast/normal/deep effort levels selected by sufficiency rather than fixed user mode


S2 accepted benchmark (pinned Wikonomi v1F + recursive FeynMap self-hosting):
adaptive search retained 100% essential recall, stopped locally on 3/5 Wikonomi
tasks and 5/5 FeynMap self-tasks, reduced Wikonomi active context from about
3,324 to 2,762 tokens versus always-on region activation, and was faster than
the always-on hybrid in the reference CI run. The controller now exposes
`fast`, `normal`, and `deep` effort levels chosen from sufficiency signals.

### S3 — Minimal sufficient context

- [x] Explicit post-activation context-selection stage
- [x] Evidence-preserving endpoint/relationship packing
- [x] Quality-retention benchmark against the same model-facing activated context
- [x] Context-compression and downstream-cost metrics

S3 accepted benchmark: `substrate-baseline` run **35962742536** at
`9781fcb0`. FeynMap self-hosting retained 100% essential recall (6/6) while
reducing model-facing context from about 7,661 to 2,948 tokens (~61.5%).
Pinned Wikonomi v1F retained 100% essential recall (5/5) while reducing
model-facing context from about 6,313 to 2,686 tokens (~57.4%). The comparison
uses the same model-facing activated payload on both sides rather than debug
metadata.

### S4 — Active state for long-horizon agents

- [x] Distinguish persistent graph memory from active working context
- [x] Reuse task regions/working context across tool calls when S2 sufficiency allows it
- [x] Re-expand or invalidate state when new evidence changes the task
- [x] Measure context growth avoided over long agent runs

S4 accepted benchmark: `substrate-baseline` run **36024684677** at
`f78c7c77`. Across two recursive FeynMap agent loops (12 steps total), the
active-state fast path served 7/12 follow-ups without a fresh graph route/search
and re-expanded on the other 5. Essential-symbol recall remained 100% (12/12).

Naively accumulating each fresh S3 context would retain 26,119 tokens. The
portable carried `ActiveState` ended at 2,439 tokens, avoiding about **90.7%**
of that retained-context growth. Even fully rehydrating every currently active
node/edge produced 9,931 tokens, still about **62.0%** below accumulated
history. The bounded state retained about 78.0% of the fresh S3 node set on
average while preserving every benchmark-essential symbol.

The accepted policy is conservative: an existing active set is reused only
when the same provider-neutral S2 sufficiency precheck says it already covers
the follow-up. Otherwise FeynMap falls back to the normal S2 adaptive retrieval
and S3 packing path. Active state stores references and compact retrieval
history rather than copied graph truth, and snapshot changes invalidate reuse.

### S5 — Tool-space routing

- [x] Represent tool capabilities as routable grounded contracts
- [x] Expose only the small relevant tool subset to the downstream model
- [x] Measure tool-schema token reduction and routing quality

### S6 — Performance implementation

- [x] Profile the Python hot path before porting
- [x] Cache only measured bottlenecks
- [x] Freeze substrate contracts
  - [x] S6.3.1 inventory current external/cross-runtime contracts
  - [x] S6.3.2 define compatibility/versioning rules
  - [x] S6.3.3 add canonical conformance fixtures
  - [x] S6.3.4 freeze accepted contract set

S6.3.4 freezes the accepted portable contract set in `feynmap/contracts.py` and
`docs/S6_3_4_FROZEN_CONTRACTS.md`. Provisional grounding/context/judgment
payloads remain explicitly outside the frozen set until separately versioned
and covered by conformance fixtures.

S6.3.3 conformance assets:
- `tests/fixtures/contracts/s6_contracts_v1.json` pins canonical semantic graph, repository snapshot, active state, tool capability/space, tool-schema-pack, and deterministic identity/digest vectors.
- `tests/test_contract_conformance.py` verifies canonical round-trips, unsupported-major and unknown-enum rejection, additive optional-field read behavior, deterministic graph/snapshot/tool identities, nested graph-version rejection, active-state snapshot binding, and model-facing tool-schema delivery.
- [ ] Port latency-critical pieces to Rust where profiling justifies it
  - [x] S6.4.1 confirm current measured hot paths
  - [x] S6.4.2 rank Rust candidates by cost, stability, and isolation
  - [x] S6.4.3 select `RegionIndex.route()` as first target and define benchmark
  - [x] S6.5.1 define Python↔Rust routing-kernel boundary
  - [x] S6.5.2 add PyO3/maturin project skeleton
  - [x] S6.6 implement native routing kernel
  - [x] S6.7 differential Python/Rust conformance
  - [x] S6.8 performance acceptance
  - [ ] S6.9 optional production fast path

S6.8 accepts the **reused route-level accelerator** from five paired, same-run
1,200-call timing samples. The complete Python→Rust→Python route achieved
21.76x on Python 3.8 (1,636.03→75.19 us) and 23.69x on Python 3.12
(1,493.48→63.05 us); both exceed the declared >=2.0x criterion. Extra
one-time preparation and native construction averaged about 10–11 ms,
recovered after approximately eight calls in those runs. Full adaptive/minimal
workflow gains are **not yet established**: normal production routing remains
Python until optional S6.9 integration and whole-workflow validation.
See `docs/S6_8_NATIVE_PERFORMANCE_ACCEPTANCE.md`.

S6.7 verifies the existing Python route, compact Python numeric reference and
compiled Rust on 12 independently expected cases, 108 seeded stress requests
and six recursive FeynMap self-hosting tasks (126 total per supported Python
interpreter). It also aligns Python/Rust invalid-input validation and records
versioned JSON conformance artifacts for the one cp38-abi3 wheel under
Python 3.8 and 3.12. See `docs/S6_7_DIFFERENTIAL_CONFORMANCE.md`.

S6.6 implements a Rust-owned `NativeRegionIndex` using validated CSR arrays,
the weighted two-pointer IDF scoring kernel, deterministic ranking and bounded
general/direct-path selection. Native CI executes the compiled code on Python
3.8 and the same `abi3` wheel on 3.12, including six recursive self-hosting
queries. The normal Python router is unchanged pending S6.7/S6.8.
See `docs/S6_6_NATIVE_ROUTING_KERNEL.md`.

S6.5.2 adds the isolated `native/routing_kernel` PyO3/maturin crate,
an optional Python loader, and CI that builds one Python-3.8 `abi3` release
wheel and imports the same binary on Python 3.8 and 3.12. No routing behavior is
native yet. See `docs/S6_5_2_PYO3_MATURIN_SKELETON.md`.

S6.5.1 defines an internal `feynmap.native_region_routing/1.0.0` ABI:
Python keeps semantic names/tokenization, transfers deterministic CSR-style
numeric arrays once, and the future Rust object receives only compact numeric
per-query requests. A pure-Python compact kernel plus the self-hosting routing
benchmark prove the boundary reproduces current routing semantics. See
`docs/S6_5_1_RUST_BOUNDARY.md`.

S6.4.3 first Rust target: deterministic region-routing lexical scoring.
The Python reference microbenchmark runs 1,200 route calls after one graph/index
build and records both timing and exact route signatures. See
`docs/S6_4_3_RUST_TARGET_SELECTION.md`.

S6.2 accepted measured optimizations:
- bounded repeated tool-routing tokenization cache (S6.2.1)
- pack-local compact node/edge payload reuse during minimal-context budget fitting (S6.2.2)
- per-file callable interval indexing for Python framework enrichment (S6.2.3)

The post-S6.2 profile leaves no comparably clear cache/index target. Python AST
indexes are already session-cached, region lexical indexing is constructed once
per graph, and the remaining token/attribute processing costs are materially
smaller. Further optimization now requires a new measured bottleneck rather
than speculative caching.

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

### Pre-Rust branch consolidation ✅

- [x] Consolidate the S0-S6 substrate line into `main`
- [x] Recover independently useful adversarial-resolution work
- [x] Close superseded stacked PRs
- [x] Park the old stdio MCP transport as an explicit draft experiment
- [x] Audit all remaining branches for unique commits/content
- [x] Preserve V2-only leftovers as an archival reference rather than an active branch
- [ ] Django/DRF permission-policy extraction as grounded V3 framework evidence
- [ ] Explicit routed/unrouted Django handler coverage in V3

See `docs/BRANCH_CLEANUP_AUDIT.md` for the branch-by-branch disposition.

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
