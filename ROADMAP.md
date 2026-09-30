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
- [x] Port latency-critical pieces to Rust where profiling justifies it (optional, not default)
  - [x] S6.4.1 confirm current measured hot paths
  - [x] S6.4.2 rank Rust candidates by cost, stability, and isolation
  - [x] S6.4.3 select `RegionIndex.route()` as first target and define benchmark
  - [x] S6.5.1 define Python↔Rust routing-kernel boundary
  - [x] S6.5.2 add PyO3/maturin project skeleton
  - [x] S6.6 implement native routing kernel
  - [x] S6.7 differential Python/Rust conformance
  - [x] S6.8 performance acceptance
  - [x] S6.9 optional production fast path (opt-in; Python default)

S6.9 integrates Rust lazily into the ordinary `RegionIndex.route()` entrypoint
behind `FEYNMAP_NATIVE_ROUTING=1` or an explicit constructor flag, retaining
the Python default and fail-open fallback for missing/mismatched/failing native
wheels. A per-index lock prevents duplicate concurrent native setup; optional
shadow verification compares each result against Python.

The first same-graph, five-pair self-hosting workload confirms identical
selected evidence, delivered tokens and essential recall (6/6):
region-first/minimal-context Python 612.729 ms vs opt-in native 615.602 ms,
with six Rust calls, one setup and no fallback. Adaptive/minimal-context
Python 500.839 ms vs opt-in 505.160 ms; all six tasks stopped locally, so
Rust performed zero calls and zero setup. This is **not a material whole-
workflow acceleration claim**: it confirms optional correctness and
conditional reuse. Python remains default. See
`docs/S6_9_OPTIONAL_NATIVE_ROUTING.md`.

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

### Post-S6 review hardening — active priority

The S6.9 Rust routing kernel is a safe **optional** acceleration path, not
a reason to port more algorithms now. An external exploratory review exposed
possible real-project graph and retrieval failures; address known crashes
and independently reproduce semantic misses before extending the substrate.
See `docs/POST_S6_EXTERNAL_REVIEW_TRIAGE.md` for exact findings and gates.

**P0 — crash-free source ingestion and repository hygiene**

- [x] Skip vendor/generated `*.min.js` by default, with diagnostics
- [x] Disambiguate same-line JavaScript symbol identity collisions using source offsets without renumbering unrelated identities
- [x] Fix malformed Rust `.gitignore` entries and remove tracked bytecode
- [x] Remove obsolete root `__init__.py` / `main_broken.py` from active checkout
- [x] Replace deprecated AST string aliases with `ast.Constant.value` in identified helpers
- [x] Pin external MDN Django, Flask microblog and DRF checkouts and capture independent semantic/route/retrieval expectations

**P1 — framework grounding: resolve before ranking**

Develop in seven individually accepted checkpoints. See
`docs/P1_FRAMEWORK_SEMANTICS_EXECUTION.md`; source-authored and pinned probes
are in `experiments/p1_external_framework_manifest.json`.

- [x] **P1.1 External baseline:** fixed MDN Django, Microblog and DRF revisions
  - [x] P1.1a Verify external source facts, pin three immutable commits and freeze an initial probe manifest
  - [x] P1.1b Run FeynMap against those exact checkouts; record current graph, missing relationships, selected context and diagnostic evidence (2/11 independent probes met; zero analysis crashes)
- [x] **P1.2 Django CBV grounding:** imported `model`, `queryset`, explicit and convention-backed template relationships
- [x] **P1.3 AppConfig hub treatment:** preserve membership evidence without polluting task-relevant impact and sparse routing
- [x] **P1.4 Django named URL resolution:** static `reverse`, `reverse_lazy`, namespace and template `{% url %}` relationships
- [x] **P1.5 Flask Blueprint composition:** resolve registrations and combine `url_prefix` with route decorators
- [x] **P1.6 DRF/diagnostics:** serializer/model/permission wiring, routed/unrouted coverage, and actionable unresolved-count separation
- [x] **P1.7 External replay:** compare all original pinned cases before/after with no fabricated relationships or recall regression

**P1.1b frozen findings (29 Sep 2026):**
`docs/P1_1B_EXTERNAL_BASELINE_RESULTS.md` and
`experiments/results/p1_1b_20260929_external_baseline.json` preserve the
2/11 result (MDN 0/6; Microblog 0/2; DRF 2/3), with exact revisions,
source evidence, route/context output, diagnostics, time and peak RSS.
MDN has 29 AppConfig membership edges but lacks the selected model/template
links and URL name; Microblog retains raw `/tokens` instead of `/api/tokens`;
DRF delivers throttling.py but not essential fields.py for the serializer
query (8/10 delivered nodes are tests). Both pinned DRF minified JS bundles
are safely skipped when the JS adapter is exercised directly. Known missing
graph facts are baseline data, not CI failures; no analyzer semantic changes
were made during P1.1b. **Next: P1.2 Django CBV relationships.**

**P1.2 accepted findings (29 Sep 2026):**
`docs/P1_2_DJANGO_CBV_GROUNDING.md` and
`experiments/results/p1_2_20260929_django_cbv.json` record a scoped MDN
improvement from **0/6 to 5/6** frozen Django probes: both model bindings,
both default templates and the explicit template now resolve. The named URL
`books` remains intentionally unresolved for P1.4. Microblog stays 0/2 and
DRF stays 2/3, confirming no cross-framework score drift. Model/queryset
bindings require import-resolved unique in-repo models; default templates are
framework-inferred only when the model and physical template are unique.
Ambiguous/dynamic/custom cases remain explicitly unresolved. **Next: P1.3
AppConfig hub semantics.**

**P1.3 accepted findings (29 Sep 2026):**
`docs/P1_3_APPCONFIG_HUB_SEMANTICS.md` and
`experiments/results/p1_3_20260929_appconfig_hub.json` document
removal of 29 synthetic MDN and 20 DRF handler→AppConfig `DEPENDS_ON`
edges while retaining all 29 and 20 inferred source-directory memberships
in non-traversable graph metadata. Original P1.2 source facts remain 5/6
MDN; the 11 external probes remain 7/11 overall. Real MDN impact at
depth one finds BookListView and BookDetailView from the Book model, but
CatalogConfig no longer creates a blanket view impact or a direct routing
locality hop. Inferred source proximity is **not** runtime registration
evidence. The new external CI gate requires zero fabricated dependency
edges, all structural observations and actual impact/locality isolation.
**Next: P1.4 named URLs and reverse resolution.**

**P1.4 accepted findings (29 Sep 2026):**
Static Django URL registrations now follow imported handler identities and
include/app namespace composition. Python reverse/reverse_lazy and literal
template {% url %} names link only to uniquely registered handlers; dynamic
and ambiguous names remain unresolved, and template tags are not HTTP
client URLs. Pinned MDN improves to **6/6** source-authored probes; the
11 independent external probes improve to **8/11** overall. All prior
P1.2 model/template and P1.3 AppConfig non-hub gates pass unchanged.
Flask remains 0/2 and DRF 2/3. Python 3.8/3.12 tests and recursive
self-check pass. See docs/P1_4_DJANGO_NAMED_URLS.md and
[external replay 36522700164](https://github.com/Roderick47/FeynMap/actions/runs/36522700164).
**Next: P1.5 Flask Blueprint prefix composition.**

**P1.5 accepted findings (29 Sep 2026):**
Only Blueprints statically traced from their constructor through a Flask
application's register_blueprint() produce exposed http_server contracts.
Literal application-registration url_prefix composes with decorator paths,
with declaration/registration provenance and original HTTP methods retained.
Unregistered or dynamically prefixed Blueprints stay unresolved; raw route
fragments do not masquerade as HTTP server endpoints. Imported Flask app
aliases, package-relative factories, multiple and nested Blueprint
registrations are covered by negative/positive regression fixtures.

The locked Microblog token POST+DELETE probes improve **0/2 → 2/2**, with
both grounded at **/api/tokens**. The independent development corpus improves
**8/11 → 10/11** (MDN 6/6, Microblog 2/2, DRF 2/3). P1.2, P1.3 and P1.4
gates pass unchanged. Python 3.8/3.12 and recursive self-check are green.
See docs/P1_5_FLASK_BLUEPRINT_COMPOSITION.md,
experiments/results/p1_5_20260929_flask_blueprints.json and
[external replay 36523511644](https://github.com/Roderick47/FeynMap/actions/runs/36523511644).
**Next: P1.6 DRF grounding and diagnostic accuracy.**

**P1.6 accepted findings (29 Sep 2026):**
A dedicated source-only DRF adapter records exact imported serializer_class,
ModelSerializer.Meta.model, literal permission_classes, declaration-only
serializer fields and explicitly source-proven Django URL/DRF router coverage
without equating absence of static registration with a definitely unrouted
runtime handler. The pinned DRF SerializerMetaclass._get_declared_fields
contains a real isinstance(obj, Field) use of the imported
rest_framework.fields.Field class. That exact source-backed USES_DATA edge
brings **both serializers.py and fields.py into activation** for the locked
serializer query; fields.py was previously absent even from activation.

The existing packer still omits fields.py from final delivered context
under its 3,200-token/24-node budget. No oracle modification or speculative
edge was used to force a false pass: external probes remain **10/11**
(MDN 6/6, Microblog 2/2, DRF 2/3); delivery-channel balancing is P2.
The improved integration report explicitly separates **54 raw unmatched**
DRF contracts into **18 potential review candidates** and **36
non-actionable/unproven**, and separately classifies **1,069** unresolved
Python builtin calls rather than treating them as missing integrations.
These counts are descriptive and the review candidates are not verified
bugs. P1.2–P1.5 external gates, Python 3.8/3.12, recursive self-check and
positive/negative DRF fixtures pass. See
docs/P1_6_DRF_GROUNDING_AND_DIAGNOSTICS.md,
experiments/results/p1_6_20260929_drf_diagnostics.json, and
[external replay 36525528345](https://github.com/Roderick47/FeynMap/actions/runs/36525528345).
**Next: P1.7 frozen external replay and acceptance, then P2 context policy.**

**P1.7 accepted findings (29 Sep 2026):**
The P1.1a immutable source-author manifest and original P1.1b result were
sealed by known Git blob identities before replay. Replaying each of the
same three exact public revisions with strict provenance, confidence and
diagnostic accounting gives **2/11 → 10/11 positive development probes**:
**8 recovered**, **0 regressed**, and **1 still unmet**.
MDN is 6/6, Microblog is 2/2, and DRF is 2/3.

The DRF serializer-to-Field relation is real source evidence and restores
both essential implementation files to sparse activation, but fields.py
remains absent from final delivered context. The immutable serializer
delivery probe therefore remains a failure pending P2. P1.7 did not
fabricate more edges, weaken the source oracle, reclassify inferred
framework convention as verified, or count normal exported endpoints
as integration errors. Source-negative adversarial fixtures, frozen S6
contract conformance, tamper/error paths, Python 3.8/3.12 and recursive
self-analysis all pass. The benchmark remains *positive-only*; its
false-positive rate and agent-repair outcomes are explicitly unmeasured.
S7 needs a genuinely separate, sealed held-out repair corpus before
making downstream accuracy claims.

See docs/P1_7_FROZEN_EXTERNAL_ACCEPTANCE.md,
experiments/results/p1_7_20260929_frozen_acceptance.json,
[acceptance replay 36526547547](https://github.com/Roderick47/FeynMap/actions/runs/36526547547)
and [full tests 36526547551](https://github.com/Roderick47/FeynMap/actions/runs/36526547551).
**P1 is closed on the accepted development set. Next: P2 context
delivery-channel budgeting and independent DRF serializer/throttling
fixtures.**

**P2 — retrieval policy and downstream context** (incremental: see `docs/P2_DELIVERY_EXECUTION.md`)

- [x] **P2.1 Opt-in source role-aware delivery:** distinguish implementation, test, migration, vendor/generated and other evidence channels; preserve the unchanged default while comparing policy selection on the exact same activated graph
- [x] **P2.2 Source-locked channel-budget comparison:** five independently authored stockroom implementation/test/migration tasks plus three pinned DRF symbol-level controls, two fixed budgets and three arms; measure exact activated-versus-delivered file/symbol labels, genuine required test/migration evidence, named distractor char/4 equivalents and single-run timings. Valid comparison revealed policy regressions, so **do not make P2.1 source-first the default**.
- [ ] **P2.3a Correct delivery sufficiency:** preserve task-relevant activated symbols and source-backed behavioral continuations, including genuinely necessary test and migration evidence; freeze new examples before tuning/re-evaluation, never read gold labels during selection.
- [ ] **P2.3b Downstream fidelity and shipping decision:** compare supported/unsupported claims and real task quality, with S7 held-out agent repairs remaining independently sealed.

P2.1's initial pinned-DRF shadow replay demonstrates the previously missing
`rest_framework/fields.py` delivered alongside `serializers.py`, using the
same graph activation and original 3,200-token/24-node/24-edge budget.
The source-first shadow currently passes both DRF implementation-file
retrieval questions while the frozen P1 default continues to score **10/11**.
This is a delivery-policy measurement, not an independent agent-task accuracy
or population false-positive claim. Implementation witnesses are selected
from activated source nodes and real stored cross-file edges only; source
channel classification never modifies graph truth.

**P2.2 accepted experiment (29 Sep 2026):**
The newly frozen source-authored stockroom cohort and reused pinned DRF
calibration contain **8 tasks**, two budgets (1,600/12/12 and 3,200/24/24)
and three policies (legacy, P2.1 source-first, balanced floor-1). All
source-authored required symbols were activated upstream (stockroom 10/10,
DRF 7/7). At the standard budget, legacy delivered **10/10 stockroom symbols
and 6/7 DRF symbols**; P2.1 source-first delivered **5/10 and 4/7** despite
using fewer estimated context tokens. Source-first retained only 1/2 required
stockroom test symbols and 0/2 required migration symbols, while legacy
retained both. The pre-registered balanced variant did not repair this
(4/10 stockroom, 5/7 DRF). One DRF test-suite symbol was omitted by all
three policies. The collector exposes 31 label-regression *occurrences* over
arms/budgets; these are not 31 unique defects or task outcomes.

The result invalidates a blanket assumption that per-file implementation
floors and a test-node cap imply good symbol delivery. Neither graph
truth, legacy default, nor the frozen P1 oracle was changed; P1 remains
10/11. Read `docs/P2_2_CHANNEL_BUDGET_COMPARISON.md`,
`experiments/results/p2_2_20260929_delivery_comparison.json` and
[full P2.2 replay 36555370204](https://github.com/Roderick47/FeynMap/actions/runs/36555370204).
The next design checkpoint is **P2.3a** task/evidence-aware sufficiency,
then P2.3b actual downstream answer fidelity.

**P3 — first usable integration surface**

- [ ] Task-oriented `feynmap context '<task>'` CLI exposing the existing SparseContextPipeline and immutable snapshot identity
- [ ] Make claim-validation/evidence status accessible in the local development workflow
- [ ] Rebuild optional read-only stdio MCP from current main; parked PR #22 is reference only

**S7 — real external AI agent validation**

- [ ] S7.1 freeze the initial eight-task SWE-bench Verified pilot with the existing R1 sealed harness
- [ ] S7.2 configure and run the current four pinned experimental agent arms
- [ ] S7.3 pre-register a separate 15–20-task held-out corpus with fair no-context and repo-map comparators; explicitly version any new comparison arms
- [ ] S7.4 record official task success, patch accuracy, unsupported claims, searches, elapsed time and *total* model/tool token cost

**P4 — packaging and controlled adoption**

- [ ] Migrate generic `py-modules` (`main`, `config`, `pipeline`, etc.) into package-qualified legacy code with clean-wheel compatibility checks
- [ ] Preserve experiment lineage before relocating old versioned ranker/repair-role modules
- [ ] Maintain proprietary licensing; define external beta access terms instead of changing the license implicitly


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
