# P2.3b — downstream answer fidelity and shipping gate

**Status:** development checkpoint complete (30 September 2026).
**Decision:** keep `symbol_evidence` opt-in and keep legacy as the default.
P2.3a substantially improved *which task-bearing symbols* survive packing,
but P2.3b shows that the current compact model-facing nodes usually do not
carry enough **source-body behavioral facts** to answer implementation
questions faithfully.

## Why P2.3b exists

P2.3a established that an opt-in symbol/evidence delivery policy can retain
more task-bearing semantic evidence than the earlier file-oriented P2.1
policy. It deliberately did **not** show that a downstream language model
answers questions more correctly, makes fewer unsupported claims, or costs
less end-to-end. P2.3b measures that missing layer without changing graph
truth, confidence tiers, the P1/P2 frozen controls, or the default packer.

## Fresh source and answer oracle

Before exporting any model-facing context or collecting any answer, P2.3b
froze `experiments/p2_3b_answer_manifest.json` (Git blob
`d136168b47939af7ce8f9440cc9abd022b777310`) and twelve source files under
`experiments/fixtures/p2_3b_fulfillment/`. The corpus is separate from P2.2
stockroom and P2.3a dispatch development cases. It includes Python
implementation, regression tests, a migration, JavaScript cross-module
behavior, explicit absence of refund behavior, and one nonexistent
`issue_refund` identifier.

The answer contract contains six source-authored questions. Five require
behavioral answers and one requires `need_more_context`. Across the five
answerable questions the oracle contains **13 required atomic claims**.
Source-authored required claims, support labels and unsupported-claim traps
exist only in the scorer index. Search, packing, and the model-facing packet
never receive them.

Both the unchanged legacy packer and opt-in `symbol_evidence` packer consume
the exact same S2 activation for each question. Tight (1600/12/12) and
standard (3200/24/24) contexts are exported for structural comparison; the
standard budget is the model-facing comparison in this checkpoint.

## Oracle-free grounded answer protocol

Each model packet contains only the question, the compact FeynMap context,
`delivery_sufficient`, `unresolved_query_identifiers`, and the strict JSON
answer contract. The answer must consist of atomic factual claims citing
actually delivered node/edge IDs or return `need_more_context`. Missing facts
are **unknown, not false**.

The committed development run uses GPT-5.6 Sol through this interactive
ChatGPT session. Because the same session had already seen the source fixture
and scoring oracle, `run.json` explicitly records
`eligible_for_shipping_decision=false`. During answer generation the outputs
were deliberately restricted to the exported packets: source-body details
remembered from fixture creation were not reconstructed to manufacture a
better score. Actual per-packet provider billing tokens are unavailable on
this surface and remain `null` rather than being estimated.

## Measured result

Reference workflow:
[run 36700106598](https://github.com/Roderick47/FeynMap/actions/runs/36700106598).
Its Python 3.8 and 3.12 P2.3b/P2.3a/P2.2/contract conformance jobs, oracle-free
packet export, downstream scoring and final shipping guard all pass as
*measurement infrastructure*. The full repository test workflow also remains
green.

| Standard-budget result | Legacy | `symbol_evidence` |
|---|---:|---:|
| Required behavioral claims | 13 | 13 |
| Required claims matched | **0** | **0** |
| Required-claim recall | **0%** | **0%** |
| Answerable tasks passing all claim gates | 0/5 | 0/5 |
| Unsupported trap hits | 0 | 0 |
| Invalid or uncited claims | 0 | 0 |
| Correct `need_more_context` control | 1/1 | 1/1 |
| FeynMap context estimate, total | 9,262 | **6,638** |
| Mean FeynMap context estimate | 1,543.67 | **1,106.33** |

The symbol-aware arm therefore cuts the deterministic compact-JSON context
estimate by **2,624 units, about 28.3%**, while remaining conservative. These
are FeynMap's char/4 estimates, **not provider tokenizer or billing tokens**.
The cost reduction is real within that estimator but cannot compensate for
0/13 downstream behavioral-claim recall.

### What the packets were missing

This result is not primarily a symbol-selection failure:

- `reserve_order` and `ensure_stock` are delivered with a real `CALLS` edge,
  but the payload does not expose the source-body fact that validation occurs
  before quantity mutation, the decrement operation, or the returned audit
  message construction.
- `apply_priority_default`, `priority_default`, and the migration regression
  test are delivered, but the compact semantic nodes do not state the literal
  `"normal"` default or the branch that preserves existing priority.
- `cancel_order`, `can_cancel`, and their test are delivered, but the `{queued,
  packed}` literal set and the absence of a refund side effect are not encoded
  as downstream evidence. Inferring them from names would violate the
  grounding contract.
- `formatShipmentStatus` and `normalizeStatus` are delivered, but the compact
  JavaScript graph does not carry the relevant call/import behavior or the
  `.trim().toUpperCase()` body semantics.

The conservative model therefore cited only facts actually represented in
the packets and did not pretend those missing body semantics were known.
That produces low recall without unsupported-claim inflation—the correct
failure mode for this diagnostic.

## Missing-identifier control

For `How does issue_refund send money back after cancel_order?`, no
`issue_refund` source exists.

Legacy packing delivered nearby cancellation symbols but reported
`delivery_sufficient=true` and no unresolved identifiers. The P2.3a
`symbol_evidence` mode reported:

- `delivery_sufficient=false`
- `unresolved_query_identifiers=["issue_refund"]`

Both committed downstream answers chose `need_more_context`, but only the
symbol-aware substrate surfaced the missing identifier explicitly. This is a
meaningful P2.3a improvement even though the broader P2.3b behavioral fidelity
gate fails.

## Relative gate versus absolute quality

The frozen comparative rule says the candidate must not regress relative to
legacy, must not add unsupported/citation failures, must handle the missing
identifier, and must not cost more without better fidelity. Because **both
arms scored 0/13**, `symbol_evidence` had no unsupported regressions, handled
the missing control and used less context, that relative metric mechanically
returns `true`.

That must not be confused with useful answer quality. After the first
nonblind development score exposed this 0%-vs-0% degeneracy, P2.3b added a
strictly more conservative **absolute shipping guard**. It does not change the
frozen source/claim oracle, model answers, or relative score; it only prevents
a future shipping decision unless the candidate also has:

- 100% required-claim recall on this gate,
- every answerable task passing,
- zero invalid/uncited claims,
- zero preregistered unsupported traps, and
- correct request-more-context behavior.

Final guard result:

- frozen comparative metric: **pass** (relative tie + lower context),
- absolute downstream-fidelity gate: **fail**,
- model run eligible for a shipping decision: **false**,
- final decision: **`keep_opt_in_absolute_downstream_fidelity_not_met`**.

## Architectural conclusion

P2.1 taught us that correct **files** are not sufficient.
P2.2 showed that correct **symbols** must survive packing.
P2.3a repaired that symbol-level failure.
P2.3b now shows that correct **symbols are still not sufficient for answers**.

The next layer should deliver a compact, source-grounded behavioral envelope
for the selected symbols: normalized source assertions and/or tightly bounded
source snippets carrying operations, literals, conditions, returns and proven
calls, with exact source locations and evidence tiers. It should preserve the
existing principle that omitted information remains unknown, not false, and
must never fabricate an unresolved relationship merely to make an answer
possible.

That should be evaluated on a **newly frozen downstream corpus** before any
attempt to promote `symbol_evidence` or a successor policy to the default.
P2.3b's six questions are now development diagnostics, not a future held-out
claim. The separate S7 agent-repair corpus remains disjoint and unused.

Machine-readable checkpoint:
`experiments/results/p2_3b_20260930_downstream_fidelity.json`.
