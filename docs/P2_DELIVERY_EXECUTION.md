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

## P2.1 — Role-aware delivery (this PR, #45)

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

**P2.2 — Independent channel-budget comparison.** Freeze new source-authored
implementation, test and migration tasks (not rewritten from P1 outcomes),
including DRF serializer/throttling controls and a separate migration case.
Compare legacy and source-first under identical per-task activation, seed,
token/node/edge caps. Record file- and symbol-level implementation recall,
genuinely required test evidence, distractor nodes/tokens, omission reasons,
and measured activation + packing latency. Test a category-specific allocation
floor/cap rather than assuming that no tests should ever be included. Decide
whether role-aware should replace the legacy default only after observing
regressions on unrelated existing S3/S6 fixtures.

**P2.3 — Downstream fidelity and policy decision.** Use independent,
preauthored source questions and actual answer evaluation to compare supported
claims, unsupported claims, correctness, requests for extra context and cost.
Preserve the independent sealed S7 agent-repair holdout for full task-level
comparisons; P2 development-set success cannot be presented as a production
hallucination-reduction rate. Ship a conservative default or retain explicit
policy selection based on measured results.

**P2 exit gate:** source-only graph unchanged; a documented per-channel policy
whose reported counts reconcile; original P1 truth/tier/URL and recursive
quality tests still pass; no gold leakage into selection; no false claim of
recall when an implementation file is activated but cannot be delivered.
