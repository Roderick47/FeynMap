# Connected context and confidence policy v2

This phase follows PR #23 and targets compact, honest grounding for LLMs.

## Connected selection

`StoredSnapshotContext.context_bundle` selects an edge and any missing endpoint atomically. Every returned non-root node is connected to the root through returned relationships. It never fills the budget with nodes and then discards their connecting edges.

Candidates are ranked by hop distance, behavioral relationships before containment/ownership/imports, evidence tier, and stable identifiers. Oversized candidates are skipped so smaller candidates can fit. Previously skipped edges can be reconsidered after another path supplies an endpoint. Returned paths respect the requested depth.

The response includes omitted node/relationship counts **within the candidate neighborhood**. These are not counts of everything outside the requested depth. The root is separate from `max_nodes`, preserving the previous contract. All budget fields are included in final size accounting. The budget remains a deterministic four-character estimate, not an exact vendor-token bound. A root that cannot fit raises an explicit error.

Evidence is ordered by its contribution to the reported tier before compaction, preventing a runtime observation from being discarded behind weaker evidence while retaining its “verified” label.

### Controlled comparison

On the same synthetic graph of one root calling 20 functions, comparing the merged implementation against this phase with identical node and edge limits:

| Approximate budget | Previous additional nodes / edges | New additional nodes / edges |
| --- | --- | --- |
| 700 | 10 / 0 | 4 / 4 |
| 1,100 | 19 / 0 | 9 / 9 |
| 2,000 | 20 / 18 | 19 / 19 |

This demonstrates improved connectivity under a budget, not measured improvement in LLM answer accuracy or a latency benchmark.

## Evidence policy 2.0.0

Numeric confidence remains a detector score, **not an empirically calibrated probability**. Tiers now depend on evidence kind and strength:

| Evidence | Highest tier |
| --- | --- |
| Runtime trace or test observation, score at least 0.95 | verified, within the observation's recorded scope |
| Static, framework or integration evidence, score at least 0.75 | supported |
| Heuristic, AI inference or repository history, score at least 0.40 | inferred |
| No evidence, insufficient score, or invalid score | unknown |

A runtime/test observation below 0.95 may be supported or inferred at the respective thresholds. Each evidence item is assessed independently. Strong heuristic evidence cannot upgrade a weak observation to verified. Edge scores additionally cap their evidence tier. The strongest eligible evidence determines the label; this is not a conflict-resolution system and does not establish universal behavior.

The current regex JavaScript adapter emits heuristic evidence. Old stored `javascript.source.*` static evidence is also capped at inferred when interpreted by the new policy.

Claim responses distinguish `evidence_found` from `supported`: an inferred or unknown graph edge exists but does not constitute supported evidence. When several edges match, the strongest evidence tier wins rather than the largest raw score.

## Related correctness and compatibility

- `find_callers` follows only `calls` and `invokes`. Containment/import relationships remain available in broad incoming impact queries. Results expose `relationship_filter`.
- The grounding tool contract is **2.0.0** because callers and claim support semantics changed. Clients should read the catalog version and handle `evidence_found` separately from `supported`.
- The analysis contract is **1.1.0**. Existing incremental planning forces a rebuild when upgrading from an older analysis contract, so changed evidence classifications are not silently skipped.
- Snapshot loading verifies the original stored JSON hash before deriving current confidence labels. Historical snapshot identity stays unchanged; derived responses use the current policy. To persist newly derived graph data, capture a new snapshot rather than re-saving it against a historical hash.
- Summary and context grounding metadata identify the confidence policy. No runtime instrumentation is added in this phase: ordinary static analysis will generally produce supported/inferred labels, not verified ones.

## Validation

134 tests pass on Python 3.12. New coverage includes tight-budget fan-out, connected paths and cycles, zero depth, oversized candidates, deterministic input ordering, count limits, evidence compaction, evidence-kind caps, mixed weak/strong evidence, invalid scores, claim support, caller filtering, legacy snapshots, and tamper detection. Existing AST deprecation warnings remain.

## Remaining limits

Selection is greedy, not globally optimal. Candidate discovery still walks the depth-bounded neighborhood before output selection; very large graphs need explicit traversal/work limits and pagination. Repository summaries have count limits but no total token limit. Confidence categories remain policy-based until tested against an independently labeled benchmark corpus. Parser accuracy, dynamic binding, integration ambiguity, conflicting evidence, and runtime coverage require further work. No complete MCP transport is introduced here.
