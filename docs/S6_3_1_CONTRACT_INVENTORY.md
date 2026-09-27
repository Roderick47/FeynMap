# S6.3.1 — Substrate contract inventory

This inventory identifies the FeynMap structures that currently cross, or are
likely to cross, process/runtime boundaries. S6.3.1 does **not** freeze or bump
any contract. It records the current surface and classifies what should be
considered by the compatibility-policy and conformance-fixture checkpoints.

## Status vocabulary

- **legacy-stable** — already documented as a stable compatibility surface;
  preserve it, but do not make it the basis of new substrate work.
- **freeze-candidate** — portable, externally meaningful, and mature enough to
  enter S6.3 compatibility/conformance review.
- **needs-envelope** — externally useful today, but missing an explicit
  versioned envelope or otherwise not ready to freeze.
- **internal** — implementation, ranking, diagnostics, timings, or policy state
  that should remain free to evolve and should not become a cross-runtime ABI.

## Canonical persistence and graph truth

| Contract | Current identifier/version | Producer / consumer | Status | S6.3.1 decision |
|---|---|---|---|---|
| Canonical semantic graph | `feynmap.semantic_graph` / `1.0.0` | `SemanticGraph.to_dict/from_dict`; snapshots, query, context, future Rust | **freeze-candidate** | Primary cross-runtime graph contract. |
| Semantic ontology | `NodeKind`, `EdgeKind`, `EvidenceKind` | adapters → semantic graph → all downstream layers | **freeze-candidate** | Freeze with semantic graph compatibility rules; enum additions need explicit policy. |
| Confidence policy | `CONFIDENCE_POLICY_VERSION = 2.0.0` | engine metadata, query/context/evaluation | **freeze-candidate** | Semantics affect interpretation of graph evidence; must be compatibility-governed. |
| Analysis contract | `ANALYSIS_CONTRACT_VERSION = 1.1.0` | engine metadata, incremental reuse guards | **freeze-candidate** | Not a JSON schema, but changes can invalidate snapshot/incremental equivalence. |
| Repository snapshot | `feynmap.repository_snapshot` / `1.0.0` | snapshot capture/store/load; future storage backends/Rust | **freeze-candidate** | Explicit portable persistence boundary. |
| File fingerprint row | nested in repository snapshot | snapshot identity/inventory | **freeze-candidate** | Freeze as a child of snapshot rather than as an independent schema. |

## Legacy compatibility graph

| Contract | Current identifier/version | Producer / consumer | Status | S6.3.1 decision |
|---|---|---|---|---|
| V2/public graph artifact | `feynmap.graph` / `1.0.0` | legacy `FeynExtractor`, `graph_schema.py`, existing external consumers | **legacy-stable** | Preserve existing v1 semver guarantees. Do not extend it as the canonical S6 substrate contract. |
| Legacy graph migration/compatibility API | graph major `1` + unversioned v0 migration | `normalize_graph`, `migrate_graph`, `schema_compatibility` | **legacy-stable** | Keep as compatibility bridge while canonical work targets `feynmap.semantic_graph`. |

The two graph families are intentionally distinguished. The older
`feynmap.graph` schema uses the historical V2 node/edge vocabulary, while
`feynmap.semantic_graph` is the current language-neutral canonical graph used
by snapshots and the sparse substrate. S6.3 must not silently merge their
version histories.

## Grounding service boundary

| Contract | Current identifier/version | Producer / consumer | Status | S6.3.1 decision |
|---|---|---|---|---|
| Grounding tool catalog/input contracts | `GROUNDING_TOOL_CONTRACT_VERSION = 2.1.0`; JSON Schema 2020-12 inputs | `GROUNDING_TOOLS`, `GroundingService`, future MCP/API/Rust adapters | **freeze-candidate** | Clear transport-neutral service contract. |
| Grounding tool result payloads | no common output schema/version | `GroundingService.call()` results | **needs-envelope** | Inputs are versioned but result shapes are not. Must be addressed before cross-runtime freeze. |
| `minimal_context` grounding result | sparse-context result plus `snapshot_id`, no envelope version | GroundingService → model/client | **needs-envelope** | De-facto external payload; cannot be treated as internal. |
| Stored context/claim/query result dictionaries | no common schema/version | `StoredSnapshotContext`, `FeynMapQuery` | **needs-envelope** | Useful service outputs, but currently tied to implementation dictionaries. |

## Integration facts embedded in the graph

| Contract | Current identifier/version | Producer / consumer | Status | S6.3.1 decision |
|---|---|---|---|---|
| `attributes.integration_contracts[]` | no schema/version; required fields currently `kind`, `target`, `confidence` plus kind-specific fields | language/framework adapters → `IntegrationResolver` | **needs-envelope** | These facts are language-neutral and affect canonical edges, but their extension vocabulary is not independently versioned. |
| Integration resolution metadata | `metadata.integration`, no version | resolver → diagnostics/grounding | **internal** | Diagnostic counts/samples should not be frozen as a wire ABI. |

## Active working state

| Contract | Current identifier/version | Producer / consumer | Status | S6.3.1 decision |
|---|---|---|---|---|
| Portable active state | `feynmap.active_state` / `1.0.0` | `ActiveState.to_dict/from_dict`, long-horizon agents | **freeze-candidate** | Explicit portable, snapshot-bound state with strict version checks. |
| Rehydrated active context | `feynmap.active_context` / `1.0.0` (currently hard-coded) | `ActiveStateRuntime.rehydrate()` → downstream agent/model | **needs-envelope** | Identifier exists, but version is not centralized and there is no reader/compatibility contract. |
| Active-state transition/metrics | no schema/version | runtime diagnostics and benchmarks | **internal** | Transition deltas and efficiency metrics should remain evolvable. |
| Active retrieval history row | nested in active state | `ActiveState` | **freeze-candidate** | Freeze only as a child of the active-state contract. |

## Tool-space contracts

| Contract | Current identifier/version | Producer / consumer | Status | S6.3.1 decision |
|---|---|---|---|---|
| Tool capability node | `feynmap.tool_capability` / `1.0.0` | declared tool contract → sparse tool router | **freeze-candidate** | Provider-neutral portable capability representation. |
| Tool capability space | `feynmap.tool_capability_space` / currently shares capability `1.0.0` | capability catalog → router | **freeze-candidate** | Needs independent compatibility decision even though version constant is shared today. |
| Tool schema pack | `feynmap.tool_schema_pack` / `1.0.0` | router/packer → downstream model/client | **freeze-candidate** | This is the intended bounded model-facing tool-definition payload. |
| Delivered tool row | nested in schema pack; underlying grounding contract version/digest included | schema pack | **freeze-candidate** | Freeze as child of schema pack. |
| Deterministic tool selection | `feynmap.tool_selection` / `1.0.0` | selector → adaptive router/benchmarks | **internal** | Scores, matched terms and ranking details are algorithm/policy diagnostics, not a durable ABI. |
| Adaptive tool routing result | no schema/version | router → schema packer | **internal** | Sufficiency reason/provider-called fields are policy state. |

## Sparse retrieval and context-selection pipeline

These payloads are useful Python APIs and some are currently exported from the
package, but they mix durable facts with algorithm diagnostics. They should not
be frozen in their current shapes.

| Contract | Current identifier/version | Status | S6.3.1 decision |
|---|---|---|---|
| Region route/result | none | **internal** | Region scores/touch ratios are routing implementation details. |
| Guided search result/trace | none | **internal** | Search trace, probabilities, provider/model and traversal stats must remain evolvable. |
| Sufficiency result | none | **internal** | Threshold/policy diagnostics are explicitly algorithm-dependent. |
| Adaptive search result | none | **internal** | Stage/effort/escalation/timing shape is policy/diagnostic state. |
| Minimal-context result | none | **needs-envelope** | Selected grounded payload and token budget outcome are externally useful; metrics/packing diagnostics should be separated from any future frozen envelope. |
| Sparse-context result | none | **needs-envelope** | Currently combines adaptive-search diagnostics with model-facing context and is exposed through the grounding service. |

## Judgment-provider boundary

| Contract | Current identifier/version | Status | S6.3.1 decision |
|---|---|---|---|
| `JudgmentQuestion.to_wire()` shape | none | **needs-envelope** | Provider-neutral wire semantics are useful, but no protocol/schema version exists. |
| `JudgmentAnswer` / `JudgmentResult` dictionaries | none | **needs-envelope** | Cross-provider normalization exists but is not versioned. |
| Python `JudgmentProvider` ABC | Python interface only | **internal** | Do not freeze a Python class ABI as the cross-runtime contract; freeze wire semantics instead if needed. |

## Explicitly outside the S6 substrate freeze

Benchmark datasets/results, experiment manifests, performance-profile outputs,
repair-evaluation schemas, CI summaries, and other research artifacts may keep
their own version tags, but they are not runtime substrate contracts and are not
part of S6.3 freezing.

Likewise, concrete Python classes, SQLite table layout, caches, scoring
algorithms, routing thresholds, timing fields, and benchmark metrics are
implementation details unless a separate public contract explicitly promotes
them.

## Inventory outcome

S6.3.2 should define compatibility rules for these groups:

1. **Canonical truth:** semantic graph + ontology + confidence/analysis semantics.
2. **Persistence:** repository snapshot and nested file fingerprints.
3. **Service inputs:** grounding tool catalog and input JSON Schemas.
4. **Portable agent/tool state:** active state, tool capabilities, and tool
   schema packs.
5. **Unversioned external payloads requiring a decision:** grounding outputs,
   integration contracts, active context, minimal/sparse context, and judgment
   wire shapes.
6. **Legacy compatibility:** preserve `feynmap.graph` v1 without treating it as
   the new canonical substrate.

No contract is newly frozen by this document. The labels above are inputs to
S6.3.2 compatibility policy and S6.3.3 conformance fixtures.
