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

## P2.4 — Grounded behavioral evidence delivery (next)

P2.3b changes the bottleneck. Correct files and correct symbols are both
necessary, but the compact node representation often exposes only identity,
location, confidence and graph relations—not the source-body fact needed by a
question. Examples include mutation order, literal values, branch conditions,
return construction and JavaScript operations.

P2.4 should add a bounded **behavioral evidence envelope** for selected
symbols without turning the context layer into raw whole-file retrieval. The
design should investigate normalized, source-backed facts and/or narrowly
bounded snippets for:

1. calls and their source ordering when statically proven;
2. assignments/mutations and affected identifiers;
3. branch predicates and literal/member sets;
4. return expressions and constructed values;
5. important constants/literals used by the selected behavior;
6. test assertions and migration operations when the task explicitly needs
   those channels;
7. equivalent JavaScript/other-language source facts through adapter-neutral
   contracts where practical.

Every behavioral item must retain exact source location/evidence provenance,
be bounded by the same downstream token budget, and remain absent/unknown when
not proven. Do not synthesize prose facts from benchmark expected answers.
Freeze a **new** source-authored downstream corpus before evaluating P2.4; the
P2.3b fulfillment questions are now development diagnostics.

After P2.4 reaches useful behavioral fidelity, run a blind provider-controlled
answer comparison before changing the default. The independent S7 agent-repair
holdout remains disjoint and should only be used for broader task-level
outcome claims.

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
  claim.
