# P2 — Evidence-channel delivery and task-relevant context

P1 grounded framework relationships and showed that a correct activated graph
is not enough when S3 delivers the wrong subset. P2 therefore changes
**delivery and downstream evidence policy**, not static graph truth. It must
never feed benchmark gold labels into selection, invent an unactivated fact,
or turn missing evidence into falsehood.

## P2.1 — Role-aware delivery (completed in PR #45)

`DeliveryChannelPolicy(mode="implementation_first")` introduced opt-in source
roles for implementation, tests, migrations, vendor/generated files,
documentation, configuration and unknown locations. It preserves activated
source identities, stored edges, endpoint integrity and token/node/edge
budgets while preferring implementation-file witnesses and limiting incidental
test-node saturation for ordinary implementation questions.

The initial pinned DRF serializer shadow recovered the previously omitted
`rest_framework/fields.py` under a smaller model-facing context. Legacy
remained the default and the frozen P1 acceptance remained 10/11. P2.1 was a
file-level delivery measurement, not downstream correctness evidence.

## P2.2 — Source-locked channel-budget comparison (completed in PR #46)

Before measuring P2.1 more broadly, P2.2 froze a separate stockroom source
fixture plus reused DRF symbol-level controls. Eight source-authored tasks,
two budgets (1600/12/12 and 3200/24/24) and three policies consumed identical
per-task S2 activation. The evaluator separately recorded activated versus
delivered files and symbols, genuinely required test/migration evidence,
individually labelled distractors and exact compact-JSON character accounting.

All required source-authored symbols were actually activated (stockroom 10/10,
DRF 7/7), isolating a delivery failure. At the standard budget legacy retained
10/10 stockroom and 6/7 DRF symbols while P2.1 retained 5/10 and 4/7. A
pre-registered balanced file-floor variant did not repair the problem.
Required tests and migrations were also lost by file-first packing.

**P2.2 decision:** do not make file-oriented source-first packing the default.
A correct file is not proof that the task-bearing method/class was delivered.
See `docs/P2_2_CHANNEL_BUDGET_COMPARISON.md` and
`experiments/results/p2_2_20260929_delivery_comparison.json`.

## P2.3a — Task-symbol and source-evidence sufficiency (completed in PR #47)

P2.3a added opt-in `DeliveryChannelPolicy(mode="symbol_evidence")`. It ranks
activated named definitions from the query, preserves actual source-backed
behavioral continuations where the graph already proves them, and requires
selected task-critical symbols/edges before declaring the packed result
sufficient. Explicit code identifiers absent from activation appear in
`unresolved_query_identifiers`; their absence yields `sufficient=False`
instead of invented context.

A newly frozen Python/JavaScript dispatch fixture contained 16 required-symbol
occurrences, of which 15 were activated. P2.3a delivered all 15 activated
symbols at both budgets versus P2.1's 10/15. Reused P2.2 controls improved to
10/10 stockroom symbols at both budgets and 7/7 DRF at the standard budget,
including required test/migration evidence. The remaining missing JavaScript
identifier was truthfully unresolved upstream.

**P2.3a decision:** symbol-aware sufficiency is a strong development correction
but remains opt-in until actual downstream answer fidelity is measured.
See `docs/P2_3A_SYMBOL_EVIDENCE_SUFFICIENCY.md`.

## P2.3b — Downstream fidelity and shipping gate (completed in PR #48)

P2.3b froze a fresh 12-file fulfillment Python/JavaScript source fixture and
six downstream questions **before exporting contexts or collecting model
answers**. Five questions require 13 source-authored behavioral claims; one
asks about nonexistent `issue_refund` and should yield `need_more_context`.
Gold required claims, source support labels and unsupported-claim traps exist
only in the scorer index and are proven absent from model-facing packets.

Legacy and `symbol_evidence` consume one identical S2 activation per question.
The downstream answer protocol requires atomic factual claims citing actually
delivered FeynMap node/edge IDs. Missing facts remain unknown rather than
being reconstructed from likely source behavior.

The committed GPT-5.6 Sol development run is explicitly **nonblind** because
the interactive session had already seen the source/oracle; it is therefore
ineligible to promote a default even if it had passed. Actual provider billing
tokens were unavailable and are not estimated.

### P2.3b measured result (standard budget)

| Downstream result | Legacy | `symbol_evidence` |
|---|---:|---:|
| Required claims | 13 | 13 |
| Matched required claims | **0** | **0** |
| Answerable tasks fully passing | 0/5 | 0/5 |
| Unsupported trap hits | 0 | 0 |
| Invalid/uncited claims | 0 | 0 |
| Correct missing-identifier control | 1/1 | 1/1 |
| FeynMap context estimate total | 9,262 | **6,638** |
| Mean context estimate | 1,543.67 | **1,106.33** |

`symbol_evidence` reduces the deterministic compact-JSON context estimate by
2,624 units (~28.3%) while staying conservative, but **0/13 behavioral-claim
recall is not usable downstream fidelity**.

The missing-identifier control remains valuable: legacy reports its nearby
cancellation context `sufficient=True`, whereas `symbol_evidence` explicitly
reports `issue_refund` unresolved and `sufficient=False`. Both conservative
downstream answers abstained.

The frozen relative no-regression comparison mechanically passes because both
arms tie at zero recall, add no unsupported/citation regressions, handle the
missing control, and the candidate is cheaper. After the first development
score exposed that 0%-vs-0% degeneracy, an additive absolute shipping guard
was added. It does **not** alter the frozen source/claim oracle, answers, or
relative score; it only prevents promotion unless the candidate has complete
required-claim recall, all answerable tasks passing, clean citations/traps and
correct need-more-context behavior.

Final gate:

- comparative metric: **pass**,
- absolute downstream fidelity: **fail**,
- model run eligible for shipping: **false**,
- final decision: `keep_opt_in_absolute_downstream_fidelity_not_met`.

Reference CI: [P2.3b run 36700106598](https://github.com/Roderick47/FeynMap/actions/runs/36700106598).
See `docs/P2_3B_DOWNSTREAM_FIDELITY.md` and
`experiments/results/p2_3b_20260930_downstream_fidelity.json`.

## P2.4a — Task-conditioned grounded behavioral evidence (completed in PR #50)

P2.4a added a bounded behavioral evidence envelope over selected symbols and a
public opt-in `TaskConditionedEvidencePipeline`. Source-backed observations
cover conditions, assignments/mutations, reads/writes, literals, calls,
returns, raises, assertions, transforms, migrations and narrow source
witnesses. A `RelevanceJudge` ranks already-extracted evidence; it cannot
create source facts or upgrade evidence confidence.

The behavioral envelope explicitly separates local source coverage from
unknown transitive/runtime behavior. Negative evidence therefore remains
scoped: absence of an explicit local call is not silently promoted into proof
that a runtime effect is impossible.

Development regression on the already-seen fulfillment fixture showed that the
body-level evidence missing in P2.3b could fit within a 2,200 estimated-token
behavioral cap. This was development evidence, not a fresh accuracy result.

## P2.4b — Fresh behavioral representation comparison (completed in PR #51)

P2.4b froze a new billing/invoice-settlement Python/JavaScript corpus before
its evaluator existed. On 15 preregistered behavioral patterns:

| Fresh representation result | `symbol_evidence` | P2.4 behavior |
|---|---:|---:|
| Matched patterns | **1/15** | **13/15** |
| Recall | **6.7%** | **86.7%** |

The missing `capture_card` control remained unresolved and all behavioral
packets stayed within the fixed cap. Two misses were preserved rather than
retuned: the overpayment condition/error pair and `retry_payment` return
delegation.

See `docs/P2_4B_FRESH_BEHAVIOR_COMPARISON.md` and
`experiments/results/p2_4b_20261001_fresh_behavior.json`.

## P2.4c — Bounded delivery repair (completed in PR #52)

P2.4c diagnosed the P2.4b misses without rewriting the fresh result. The
overpayment policy symbol had already been activated but was dropped by S3;
the retry wrapper return had been extracted but was dropped by behavioral
packing.

The opt-in task-conditioned pipeline now permits a one-best source-backed
continuation to **one already-activated dependency** and preserves relevant
condition→raise pairs plus explicitly named wrapper returns. The continuation
cannot discover an unactivated node, cannot promote AI-inferred evidence and
cannot escape the original S3 budget.

On the already-seen P2.4b corpus this repair reached 15/15 with only one added
node/edge across all seven tasks. That 15/15 remains a development regression
result; the canonical fresh P2.4b measurement is still 13/15.

See `docs/P2_4C_BEHAVIOR_GAP_DIAGNOSTICS.md`.

## P2.4d — Fresh downstream validation (current checkpoint)

P2.4d froze a new rollout/deployment fixture at source commit
`3d34727a39275576cfbff3f630bf8b1998e70a0b`, then froze its oracle at commit
`15e3c361a852c985b8a36759ddebdfe94768723c` with manifest Git blob
`153bd1d1e0912c6b008ac8b0ba00c76c3529662e`. The evaluator was added only
after both freeze boundaries.

The first completed representation replay uses identical activation for
`symbol_evidence` and the repaired task-conditioned arm. Across 17 required
behavior patterns:

| Fresh P2.4d representation | `symbol_evidence` | repaired P2.4c |
|---|---:|---:|
| Matched patterns | **0/17** | **16/17** |
| Recall | **0.0%** | **94.1%** |
| Missing `force_promote` control | pass | pass |

The preregistered representation gate passed. One fresh miss is preserved:
`oversized-batch-regression` did not receive the exact
`batch_size > release.remaining_hosts` policy condition. A separate diagnostic
also records an irrelevant cross-language continuation on the JavaScript task;
that did not reduce required-pattern recall and is not repaired on this corpus.

A GPT-5.6 Sol answer run in the same oracle-exposed interactive session was
used only to exercise the downstream packet/scorer contract. It is explicitly
**not shipping-eligible**. Diagnostic results were:

| Nonblind downstream diagnostic | `symbol_evidence` | repaired P2.4c |
|---|---:|---:|
| Required answer claims | 20 | 20 |
| Grounded matched claims | **0/20** | **19/20** |
| Fully passing answerable tasks | **0/7** | **6/7** |
| Unsupported traps | 0 | 0 |
| Invalid/uncited claims | 0 | 0 |
| Missing-context control | 1/1 | 1/1 |

The candidate meets the numerical accuracy/safety thresholds in this
**nonblind diagnostic**, but both downstream promotion gates remain false
because eligibility requires an oracle-blind provider/model run. Therefore the
legacy default is unchanged and `TaskConditionedEvidencePipeline` remains
opt-in.

The next P2.4d evidence should run the already-frozen oracle-free packets
through a model/provider process that has not seen source gold, then score the
answers with the existing frozen scorer. Do not tune P2.4c against this corpus.
A later P2.4e may compare deterministic relevance with a real
`JudgmentProvider`-backed low-cost learned judge.

See `docs/P2_4D_FRESH_DOWNSTREAM_VALIDATION.md` and
`experiments/results/p2_4d_20261001_fresh_downstream.json`.

## P2 invariant/exit gates

- static graph/source truth remains unchanged by delivery policy;
- selected context never escapes activated grounded evidence;
- no benchmark gold labels are selection inputs;
- file, symbol and behavioral-evidence coverage are reported separately;
- missing evidence is unknown, not false;
- exact budgets and edge endpoints reconcile;
- original P1 truth/tier/route controls and recursive quality tests remain
  green;
- no default promotion from a merely relative win when absolute downstream
  fidelity is inadequate;
- no P2 development result is presented as an S7/general hallucination-rate
  claim;
- a downstream shipping/default claim requires an oracle-blind eligible model
  run, not an interactive session that has seen the oracle.
