# P2 — Evidence-channel delivery and task-relevant context

P1 grounded framework relationships and proved that the DRF source graph
activates both serializer implementation files. The remaining P1.7 failure is
downstream: the S3 minimal context packer gave most of the delivered node
budget to test cases while omitting the activated `rest_framework/fields.py`.

P2 changes **delivery policy**, not static graph truth. It must not rely on
benchmark gold labels at selection time or silently re-score the frozen P1
development positives. Its independent controls include actual activated
versus delivered implementation files, tests/migrations/vendor channels,
evidence-tier consistency, context tokens, supported claims and task outcomes.

## P2.1 — Role-aware delivery (completed in PR #45)

Source location maps each activated node to a conservative delivery role:
implementation, test, migration, vendor/generated, documentation, configuration, or unknown for missing locations. Classification is path-only; it cannot create a dependency or
downgrade an otherwise valid source node. Migration wins over test path
collisions; generated/vendor wins over nested test names.

`DeliveryChannelPolicy(mode="implementation_first")` is an **opt-in** policy
passed to `SparseContextPipeline.concept`, `from_node` or
`MinimalContextPacker.pack` via `delivery_policy=`. The P1/S3 default,
serialized payload shape, graph and frozen source oracle stay unchanged.

At selection time the policy:

1. Inspects the task text for explicit test/migration/vendor intent;
   otherwise treats the request as implementation-oriented.
2. Prioritizes distinct *already activated* source-file witnesses, including
   actual source-evidenced cross-file behavioral dependencies. It has no access
   to the evaluator's `essential_files` labels, repository-specific exceptions,
   or the frozen manifest.
3. Reserves at least two activated implementation-file witnesses for ordinary
   implementation requests when they exist, before admitting optional test
   enrichment. Explicit test/migration/vendor requests retain corresponding
   relevant channel nodes and one implementation witness.
4. Caps incidental test-node saturation at 35% of the requested node budget
   for non-test questions. The cap is on **nodes**, not falsely presented as a
   token allocation.
5. Preserves the activated graph restriction, exact source node and stored
   edge evidence, atomic edge endpoints, query anchors, the requested token,
   node and relationship budget, and a truthful insufficient flag when a
   critical source witness cannot fit. If a long test-only search-parent path
   does not fit, the activated implementation is exposed as an explicit
   separate grounded anchor rather than fabricated provenance.

The P1 runner now computes both packing variants on the **same activation**.
The role-aware measurements are additive
`observed.p2_role_aware_shadow`; frozen P1 `passed` still depends on
unchanged legacy packing, preserving the P1.7 10/11 result. The collector
independently checks that both locked DRF retrieval questions deliver their
essential implementation files in the opt-in shadow, all chosen IDs originate
in activation, actual endpoints accompany delivered edges, all budgets hold,
source file role counts reconcile and the existing P1.2–P1.7 gates remain
green. Synthetic positive and adversarial fixtures cover explicit test/
migration/vendor intent, channel classification and cannot-deliver-unactivated
behavior.

**P2.1 is an implementation-recall and delivery-selectivity measurement, not
a claim that model-answer correctness, precision or agent repair accuracy has
been established.** The independent framework source labels are used to
score the resulting delivery only, never to choose context.

## Remaining incremental checkpoints

**P2.2 — Source-locked channel-budget comparison (completed with measured
regressions).** The frozen independent stockroom source fixture and reused DRF
calibration yield eight preauthored queries with explicit essential source
files, finer-grained symbols, required tests/migrations, optional useful
support, and individually named irrelevant nodes. The source file blobs and
manifest Git digest were locked *before* the experiment. The runner rechecks
the literal source AST declarations and pinned revision rather than scoring
its own graph as gold.

Three packers (unchanged legacy, P2.1 source-first, and a pre-registered
balanced floor/cap variant) consume one *identical* activation per query under
1,600-token/12-node/12-edge and 3,200-token/24-node/24-edge budgets. Reports
distinguish not-indexed, not-activated, activated-but-omitted and delivered
source symbols, per-channel JSON character contribution and named
distractors; common token/edge metadata reconciles exactly under the
deterministic estimator. No model outputs are scored.

All required source-authored symbols were actually activated in both cohorts
(stockroom 10/10, DRF 7/7). At standard budget, legacy retained 10/10
stockroom and 6/7 DRF symbols; P2.1 source-first retained 5/10 and 4/7,
respectively. Source-first omitted both required migration symbols and one
of two required stockroom test symbols, despite lower estimated context.
The balanced floor/cap did not resolve the problem (4/10 and 5/7).
**Do not change the default.** Source role/file coverage alone is an
insufficient criterion for delivering the actual task-bearing symbol.
See `docs/P2_2_CHANNEL_BUDGET_COMPARISON.md` and
`experiments/results/p2_2_20260929_delivery_comparison.json`.

**P2.3a — Task-symbol and source-evidence sufficiency (implemented,
opt-in; PR #47).** The separate `symbol_evidence` mode selects actual
activated named definitions matched by the task, bounded partly matched
source methods, and existing source-evidenced behavioral-edge continuations.
It requires every selected critical *symbol and relationship* before
claiming context sufficiency. It separately recognizes explicit snake_case,
camelCase and PascalCase identifiers absent from S2 activation, reports them
in additive `unresolved_query_identifiers` diagnostics, and sets
`sufficient=False` instead of fabricating missing upstream evidence.

An independently preauthored mixed Python/JavaScript dispatch source fixture
(12 sealed source blobs and 8 source-authored queries, manifest Git blob
`0512100c4a1c76969e1cfc1c8bc16d6c0fa42e18`) was frozen before
implementation. The original P2.2 stockroom/DRF cohorts remain explicitly
reused diagnostics, not a newly held-out score. Final exploratory refinements
were informed by development replay and are described transparently in
`docs/P2_3A_SYMBOL_EVIDENCE_SUFFICIENCY.md`.

The fresh fixture yielded 15/16 required-symbol activations and P2.3a
delivered all 15 activated symbols under 1,600- and 3,200-token limits,
against P2.1's 10/15. The remaining JS `normalizeSeverity` source name
was absent upstream and must trigger a new S2 expansion, not false S3
coverage. Previously frozen P2.2 controls improved to 10/10 stockroom
symbols at both caps, including essential tests and migrations; DRF reached
6/7 at 1,600 tokens (a remaining omission is explicitly insufficient)
and 7/7 at 3,200 tokens, including previously omitted required test
evidence. The original graph, baseline scores, budget limits and default
packing remain unchanged; P2.3b is still needed before considering a default
promotion.

**P2.3b — Downstream fidelity and shipping decision.** Compare actual
supported/unsupported model claims, answer correctness, follow-up evidence
requests and cost using preauthored questions. Keep the independent sealed
S7 repair holdout disjoint and do not present a development-set improvement
as a general hallucination-reduction percentage. Ship a validated default
or retain explicit policy selection based on measured evidence.

**P2 exit gate:** source-only graph unchanged; a documented per-channel policy
whose reported counts reconcile; original P1 truth/tier/URL and recursive
quality tests still pass; no gold leakage into selection; no false claim of
recall when an implementation file is activated but cannot be delivered.
