# P2.4c — behavioral gap diagnostics and bounded repair

P2.4c is a **development** slice following the fresh P2.4b checkpoint. It does
not create a new fresh benchmark result. Its job is to diagnose the two
behavioral evidence patterns that P2.4b preserved as misses and correct the
underlying architectural gaps without tuning the historical P2.4b score.

The canonical fresh P2.4b result remains **13/15 (86.7%)** required behavioral
patterns. P2.4c reuses that now-seen corpus only as a regression fixture.

## Diagnosis

### 1. Overpayment condition + error

P2.4b missed the source-backed relationship:

```python
if payment_cents > outstanding_cents:
    raise OverpaymentError(...)
```

The post-hoc activation trace showed that this was **not** an activation failure.
`ensure_payment_allowed` was present in the S2 search at depth 2 through a real,
source-backed `CALLS` chain. The P2.3a `symbol_evidence` packer omitted that
symbol, however, so P2.4a had no legal source body from which to extract the
condition and raise.

Classification:

> **S3 symbol-delivery loss after successful activation.**

The correct repair is therefore not to invent a behavioral observation or widen
source scanning beyond the selected/activated region. P2.4c adds a tiny
post-S3 continuation that can retain an omitted behavioral dependency **only if
S2 already activated it and a source-backed relationship reaches it**.

### 2. `retry_payment` delegation

For:

```python
def retry_payment(status):
    return can_retry(status)
```

P2.4b selected both `retry_payment` and `can_retry`. The source extractor also
correctly emitted both observations:

- `call can_retry(status)`;
- `return can_retry(status)`.

The test-oriented behavioral packing policy retained the nested call but dropped
the enclosing return. This weakened the downstream fact from "returns/delegates
to `can_retry`" to merely "calls `can_retry`".

Classification:

> **Behavioral packing loss after successful symbol delivery and extraction.**

P2.4c therefore preserves the `RETURN` observation of an explicitly named
wrapper on test-oriented tasks.

## Repair 1 — one-best activated dependency continuation

`BehavioralSymbolContinuation` sits only inside the opt-in
`TaskConditionedEvidencePipeline`. It does not modify P2.3a or the legacy
`SparseContextPipeline`.

The production composition is intentionally stricter than the generic helper's
maximum capability:

- at most **one** seed anchor;
- at most **one** added symbol;
- at most two source-backed hops;
- the target must already occur in the S2 activation result;
- only outgoing `CALLS`, `INVOKES`, `VALIDATES`, or `USES_DATA` relationships;
- the relationship must carry source-located `STATIC`, `TEST`, or `RUNTIME`
  evidence;
- `AI_INFERENCE` does not qualify for continuation;
- the original S3 token/node/edge budget remains authoritative;
- a graph node that was not activated cannot be discovered by this layer.

The continuation therefore behaves as a bounded **delivery repair**, not a
second search stage.

## Repair 2 — preserve causal source witnesses

`TaskConditionedBehavioralContextBuilder` adds two test-oriented packing rules:

1. when a source-backed `RAISE` observation records an enclosing condition, keep
   the matching `CONDITION` and `RAISE` as a causal pair rather than independently
   ranking them away from each other;
2. when a task explicitly names a wrapper function, preserve that wrapper's
   `RETURN` observation in addition to a nested call observation.

Both rules operate only on source observations the extractor already produced.
They cannot create a behavior, relationship, confidence tier, or runtime claim.

## Safety regressions

`tests/test_p2_4c_behavior_gaps.py` verifies that:

- the already-activated validator can be retained for a natural-language test
  question;
- the overpayment condition and `OverpaymentError` causal pair reaches the final
  behavioral envelope;
- `retry_payment` keeps both the nested call and its enclosing return;
- nonexistent `capture_card` remains unresolved and insufficient;
- P2.4c does not newly admit or promote an AI-inferred relationship;
- a node absent from S2 activation cannot be added by continuation;
- the continuation cannot escape the original sparse token/node/edge budget.

The full repository suite is also required on Python 3.8 and 3.12, together with
recursive FeynMap self-analysis.

## Development replay

The repaired public pipeline was replayed against the **already-seen** P2.4b
billing corpus. This is regression evidence only.

| Measure | P2.4b fresh checkpoint | P2.4c development replay |
| --- | ---: | ---: |
| Required behavioral patterns available | **13/15** | **15/15** |
| Missing `capture_card` control | pass | pass |
| Sparse cap | pass | pass |
| Behavioral 2,200-token cap | pass | pass |

The 15/15 value must **not** replace the P2.4b 13/15 fresh result in product or
accuracy claims.

After constraining continuation to one best activated dependency, the seven-task
development replay measured:

- mean sparse context: **1,072.71** estimated tokens;
- mean behavioral envelope: **2,093.71** estimated tokens;
- mean combined packet: **3,171.57** estimated tokens;
- total continuation additions: **1 node / 1 edge** across all seven tasks;
- the sole addition was `ensure_payment_allowed` for the overpayment regression
  question.

The earlier unconstrained development attempt also reached 15/15 but added eight
nodes/eight edges and averaged ~1,277.86 sparse / ~3,389.57 combined estimated
tokens. Tightening to one best continuation therefore reduced mean sparse context
by about **16.1%** and combined context by about **6.4%** while retaining the
same development regression coverage.

All token figures above are FeynMap's deterministic compact-JSON
`ceil(chars/4)` estimates, not provider billing tokens.

Machine-readable checkpoint:

`experiments/results/p2_4c_20261001_development_repair.json`

Focused validation workflow:

`36814561121`

## What P2.4c establishes

P2.4c establishes a narrower architectural correction:

> Once FeynMap has activated a source-backed behavioral dependency, the
> task-conditioned evidence layer can retain one omitted dependency when needed,
> and can preserve causal/return source witnesses that flat per-kind ranking
> would otherwise split apart.

It does **not** establish:

- fresh 100% representation recall;
- downstream LLM answer accuracy;
- a hallucination-reduction percentage;
- learned-judge superiority;
- a reason to change the legacy product default.

## Next checkpoint

The next evaluative checkpoint must freeze a **new corpus before running the
repaired P2.4c pipeline**. A useful next comparison should combine:

1. fresh behavioral evidence availability;
2. downstream answer fidelity under source-citation constraints;
3. deterministic relevance versus a real configured judgment provider (Jev or a
   compatible Laya/Jeff-style adapter) on the same extracted candidate evidence.

S7 remains sealed and disjoint.
