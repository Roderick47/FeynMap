# P2.3a — Activated task-symbol and source-evidence sufficiency

**Scope:** An opt-in alternative to the P2.1 *file-representative* delivery
policy. Never changes original P1 source graph facts, frozen P1.7 10/11
acceptance, P2.2 experimental oracle, confidence tiers, or legacy default.
P2.2 PR #46 is still open: P2.3a PR #47 is stacked on its branch and must
not be merged onto `main` independently of the base.

## Motivation from the separately frozen P2.2 negative experiment

P2.1's source-first policy could deliver the correct `migrations/0001...`
and `models.py` files, yet omit the exact activated migration function and
model default required by the task. File coverage and source-role node count
are therefore **not** equivalent to answer-bearing symbol coverage. Under
P2.2's standard cap, the legacy packer delivered 10/10 required symbols in
the new stockroom cohort, while the P2.1 implementation-first policy
delivered only 5/10; the latter also dropped genuinely necessary tests and
migrations despite saving deterministic estimated context tokens.

## P2.3a selector — graph-only, never reads scoring labels

Pass `DeliveryChannelPolicy(mode="symbol_evidence")` explicitly to the
ordinary `MinimalContextPacker.pack` or `SparseContextPipeline.concept`
and `from_node` APIs. No-policy behavior is unchanged, and the previous
`mode="implementation_first"` remains available.

1. Tokenize explicit source names in the task across snake_case, camelCase
   and PascalCase, without rewriting underlying graph objects or names.
2. Rank **activated named definitions**, not arbitrary file representatives,
   by explicit name match, overlapping meaningful identifier terms,
   already-known search relevance and the request's evidence channel.
3. Retain bounded partly matched *source symbols* for case-specific policy
   methods, composite test/migration tasks, and class-qualified activated
   methods whose source role is task-relevant. This handles imported/dynamic
   boundaries **without fabricating a static call**.
4. Follow a short, bounded set of actual activated behavioral continuations.
   Require actual stored source-located STATIC / TEST / RUNTIME evidence to
   designate an edge as source-critical. AI-inferred or heuristic edges do
   not become source-backed simply because a location was attached.
   Edges always enter with their real two endpoints and original confidence
   tier. Missing edges are unknown, not invented.
5. A policy-specific sufficiency flag requires **all selected critical
   symbol witnesses and source-backed critical edges**, rather than only
   the best file witness. Continue the original 900-token initial cap
   through bounded growth as necessary; if a critical item does not fit,
   return the bounded context with `sufficient=False`.
6. Explicit code-shaped identifiers requested in the query but *absent
   from the already activated S2 result* appear in the additive
   `unresolved_query_identifiers` field. That too forces
   `sufficient=False`. Do not spend larger S3 budgets pretending they
   can repair a retrieval gap; the upstream activation needs another pass.

The role-specific incidental-test limit and the original exact model-facing
payload schema remain in place. An explicitly requested test/migration is
positive task evidence, not universal noise. The contract still uses
FeynMap's compact JSON characters/4 token *estimate*, not a vendor tokenizer
or source-code byte excerpts.

### API

```python
from feynmap import DeliveryChannelPolicy, SparseContextPipeline
from feynmap.minimal_context import MinimalContextBudget

result = SparseContextPipeline(graph).concept(
    "How does assign_ticket call check_capacity before assigning an owner?",
    context_budget=MinimalContextBudget(
        max_tokens=3200, max_nodes=24, max_edges=24,
    ),
    delivery_policy=DeliveryChannelPolicy(mode="symbol_evidence"),
)

# result.context.sufficient is a delivery/evidence-sufficiency signal, not
# a claim that an LLM answer will necessarily be correct.
# result.context.unresolved_query_identifiers shows explicit code names
# missing from upstream activation, if any.
```

## Source freeze and replay protocol

Before writing this P2.3a policy, a *new* checked-in mixed-language dispatch
fixture was source-authored and sealed: 12 Python/JavaScript source files in
`experiments/fixtures/p2_3a_dispatch` with exact individual Git blob
identities and an eight-question expected-source manifest at
`experiments/p2_3a_source_manifest.json`
(immutable Git blob:
`0512100c4a1c76969e1cfc1c8bc16d6c0fa42e18`).

New cases cover separate service/policy calls for dispatch assignment and
escalation, an actual regression test, priority migration and its regression
test (including a deliberate dynamic import), close authorization, a
two-module JavaScript alert calculation, and its JavaScript test.
The runner rejects any changed source blob or altered sealed manifest,
verifies Python AST and explicitly declared JS function source names
**independently of FeynMap's own graph**, and runs **one identical S2
activation per task** into all three policies:

- Original legacy default.
- Unchanged P2.1 source-first mode.
- New opt-in P2.3a symbol-evidence mode.

All three pack at the *same* tight 1,600-token / 12-node / 12-edge and
standard 3,200-token / 24-node / 24-edge budgets. Gold
`required_files`/`required_symbols` are examined solely **after**
packing. The runner audits that no selected node/relationship was absent
from activation, all endpoints exist, source graph identity remains intact,
per-channel compact-JSON characters reconcile, and measured content stays
within budget. Separate independent quality checks fail CI for falsely
sufficient context or lost required evidence, with known limited-budget
exceptions explicitly reported rather than hidden.

The new corpus was indeed frozen before the first policy implementation.
**However, subsequent exploratory selector refinements were informed by
the first replay and by the known P2.2 failures**: the final P2.3a readout
is a transparent source-authored **development and regression result**, not
unseen held-out generalization or an S7 agent benchmark. The P2.2 stockroom
and DRF controls are explicitly flagged as *reused nonfresh diagnostics*.

## Observed source-level outcomes

The separate new mixed-language corpus had **16 required-symbol
occurrences**, of which **15 were activated**; all 15 activated symbols
were delivered by both the original legacy selector and the new
symbol-evidence selector under the tight and standard caps. The P2.1
file-first selector delivered 10 of those 15 under either cap.
The missing 16th symbol is JS `normalizeSeverity`: it is present in
the pinned fixture's `client/severity.js` source but not activated by
the current upstream search for the `formatTicketAlert` query.
P2.3a does **not** synthesize the missing import relation or claim
retrieval success; its explicit-symbol check marks the context insufficient.

Previously frozen P2.2 controls (reused diagnostic evidence, *not* fresh):

| Cohort | Cap | Legacy | P2.1 file-first | P2.3a symbol-evidence |
|---|---|---:|---:|---:|
| Stockroom (10 required symbols) | 1,600 | 9/10 | 5/10 | **10/10** |
| Stockroom | 3,200 | 10/10 | 5/10 | **10/10** |
| DRF (7 required symbols) | 1,600 | 3/7 | 4/7 | **6/7** |
| DRF | 3,200 | 6/7 | 4/7 | **7/7** |

The old stockroom's **2/2 task-required test symbols and 2/2 migration
symbols** survive the new mode at both budgets; P2.1 kept 1/2 and 0/2.
In DRF, the newly scored `SimpleRateThrottleTests` class survives
in P2.3a (1/1), although the legacy/P2.1 context omitted it.
One activated `SimpleRateThrottle.allow_request` method remains absent
at the tighter 1,600-token cap: P2.3a sets `sufficient=False` for that
specific case. At 3,200 tokens it is delivered. This remains a real,
recorded per-symbol tradeoff, not an assertion of universal non-regression.

The model-answer layer has **not** been called. Neither these data nor
deterministic context savings establish claim correctness, hallucination
prevalence, actual tokenizer billing, production repair success, or
performance distributions.

## Acceptance and next step

The new mode remains **opt-in** pending P2.3b. Full backward compatibility
also runs the original P1.2–P1.7 external fixture gates, frozen S6 contracts,
P2.2 original three-policy results, Python 3.8/3.12 tests and recursive
FeynMap analysis. P2.3b must freeze genuinely *new* prompts and evaluate
actual downstream factual claims, unsupported statements, requests for
expansion and end-to-end cost before considering a default policy.
Separately, upstream JS cross-file activation for `normalizeSeverity`
is a source/adapter issue and must not be disguised as S3 delivery success.
