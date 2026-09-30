# P2.4 — grounded behavioral evidence and task-conditioned relevance

P2.3b established a stricter boundary than the earlier delivery experiments:
choosing the right source file is insufficient, and even choosing the right
symbol is insufficient when the downstream packet omits the source behavior
that answers the task. P2.4 adds a bounded behavioral layer **without changing
canonical semantic-graph truth or the legacy/default delivery path**.

## Architecture

The opt-in pipeline is:

```text
natural-language task
        |
        v
S2 semantic activation
        |
        v
P2.3a symbol_evidence delivery
        |
        v
source-backed behavioral extraction
        |
        v
task-conditioned relevance judgment
        |
        v
bounded behavioral envelope + explicit unknowns
        |
        v
downstream LLM / agent
```

The public composition surface is `TaskConditionedEvidencePipeline`. Existing
`SparseContextPipeline` callers are unchanged.

## Truth and relevance are different responsibilities

The source analyzer decides what evidence exists. A relevance judge decides
which already-grounded observations matter for the current task. The judge
cannot:

- add a source observation;
- change a node/edge;
- increase an observation's evidence confidence;
- convert JavaScript heuristic evidence into supported static evidence;
- override an unresolved requested identifier;
- override behavior omitted by a critical evidence budget.

`DeterministicRelevanceJudge` is the reproducible baseline. The optional
`JudgmentProviderRelevanceJudge` uses FeynMap's existing provider-neutral
`JudgmentProvider` contract. The existing Jev adapter can therefore rank
relevance now; future Laya/Jeff-style adapters require no graph or P2.4 schema
change. Provider failure falls back to the deterministic judge.

## Behavioral observations

`GroundedBehaviorExtractor` inspects only source spans for symbols already
selected by S3. Each observation has a stable ID, selected-symbol ID, kind,
summary, exact source location, evidence record/confidence tier, local source
order, optional enclosing condition, and a bounded source witness.

The initial language-neutral observation kinds are:

- parameter;
- metadata/decorator;
- read;
- assignment;
- mutation;
- condition;
- call;
- return;
- raise;
- assertion;
- transform;
- side effect;
- migration operation.

Python observations use AST-backed static evidence. JavaScript/TypeScript
observations retain the existing conservative `javascript.source.*` evidence
semantics and therefore remain inferred rather than silently upgraded.

The envelope also derives compact structured facts from each exact witness:
reads, writes, literals, operators, call expressions, and transform chains.
For example, `item.quantity -= requested_quantity` records `item.quantity` as
both read and written; `.trim().toUpperCase()` retains both transforms.

## Ordering

Every observation carries its selected `symbol_id` and local source `order`.
This supports grounded statements such as a validation call appearing before a
mutation and return **within the same symbol** without duplicating a separate
sequence index. It does not claim global runtime ordering, concurrency
ordering, or dynamic call ordering merely from source position.

## Tests and migrations are evidence channels, not noise

P2.4 applies the P2.1/P2.2 lesson one level deeper. A generic relevance sort
can still let one evidence channel crowd out the causal path. Before normal
packing, the behavioral packer reserves only the behavior/channel pairs needed
by the task type rather than every high-scoring observation:

- ordinary implementation/state tasks reserve relevant implementation calls,
  conditions, mutations and returns;
- test tasks reserve production causal behavior **and** test assertions/calls;
- migration tasks reserve migration guards/writes/calls/returns **and** relevant
  implementation/default behavior;
- transformation tasks reserve calls/transforms/returns;
- side-effect tasks reserve explicit effects/calls plus the relevant return,
  condition or mutation witnesses.

When the question explicitly names multiple code symbols, P2.4 reserves a
matching witness for each named symbol where that required behavior dimension
exists. This prevents one relevant function from displacing another under a
fixed budget.

Remaining budget is spent essential → supporting → uncertain. Explicitly
irrelevant observations are omitted. Under uncertainty, FeynMap favors recall
rather than treating uncertain as false.

## Coverage and negative evidence

A selected symbol's complete source span is inspected by the supported local
extractor. The model-facing envelope states the limit of that guarantee:

- local source scan: complete for the supported extractor;
- transitive runtime behavior: not claimed complete;
- dynamic dispatch: unknown unless separately evidenced;
- external side effects: unknown unless separately evidenced.

Therefore the absence of a refund call in a scanned local function can support
"no explicit refund operation appears in this body". It cannot by itself
support "no refund can occur anywhere at runtime" when unresolved or external
callees remain.

The packet reports requested identifiers that were unresolved upstream,
critical behavior omitted by budget, supporting/uncertain evidence omitted by
budget, and call targets whose behavior is not present among selected symbols.
This preserves the project rule: **unknown is not false**.

## Budget discipline

`BehaviorEvidenceBudget` separately caps behavioral observations, inline source
witness characters, and the deterministic compact-JSON token estimate. The
**complete final behavioral envelope** — observations, task/selection metadata,
coverage/unknowns, provenance and sufficiency — is checked against the
behavioral token cap. Lowest-value noncritical enrichment is removed first. If
an extremely small budget cannot retain critical evidence, P2.4 drops evidence
and marks the packet insufficient rather than silently exceeding the cap.

The model-facing row is intentionally more compact than the internal
`BehaviorObservation`: rich evidence/relevance objects remain available to the
runtime while the packet carries the exact source range, confidence tier,
compact provenance, relevance label/score, structured source facts and minimal
source witness.

The base S3 context estimate and P2.4 behavior estimate remain deterministic
`ceil(chars/4)` approximations, not vendor tokenizer/billing tokens.

## Sufficiency

The deterministic judge asks whether the selected behavioral dimensions are
enough for the task type. Examples include conditions/raises for failure
questions, mutations for state-change questions, assertions for test
questions, returns/transforms for transformation questions, and calls/effects
for side-effect questions.

A learned provider may make a softer sufficiency judgment only after hard
source constraints pass. It cannot overrule unresolved explicit identifiers
or missing critical behavior.

## Development replay result — 30 Sep 2026

The original P2.3b fulfillment corpus is now a **development regression
fixture**, not a fresh held-out set. P2.4 deliberately reuses it to test whether
the facts that were absent from P2.3b can now survive a bounded behavioral
packet.

At a fixed behavioral cap of **2,200 estimated tokens**, the final development
replay retained every predeclared body-level regression witness across all five
answerable tasks:

| Development task | Previously missing behavior now represented |
| --- | --- |
| reservation implementation | `ensure_stock`, quantity decrement, returned `reservation_message` |
| insufficient-stock regression | comparison condition, `InsufficientStock`, unchanged-quantity assertion |
| priority migration | missing-key guard, conditional priority write, `"normal"` default |
| cancellation policy | `cancel_order -> can_cancel` return and `{queued, packed}` literals |
| JavaScript status | `normalizeStatus`, `.trim().toUpperCase()`, `SHIPMENT:` construction |

Result: **5/5 known development pattern tasks pass**, with **0 critical
behavior observations omitted** in those task packets. The deliberately
nonexistent `issue_refund` control remains unresolved and the combined packet
remains insufficient rather than fabricating refund behavior.

Across the six development tasks:

- mean behavioral envelope: **2,147.5 estimated tokens**;
- mean combined sparse + behavioral context: **3,259 estimated tokens**;
- every behavioral packet stayed at or below the 2,200-token cap;
- missing-identifier control: **pass**.

See `experiments/results/p2_4_20260930_development_behavior.json` and workflow
`36712872733`.

This is **representation/regression evidence only**. The fixture, expected
patterns and source were inspected while implementing P2.4, so these numbers
must not be reported as independent downstream model accuracy, hallucination
reduction or a shipping/default result.

## Next measurement gate

Before making a new default/shipping claim:

1. freeze a separate P2.4 source corpus, question set and answer/evidence oracle
   before inspecting any result;
2. compare `symbol_evidence` alone against deterministic task-conditioned
   behavioral evidence on the same activation;
3. optionally compare a provider-backed relevance judge (Jev first; Laya/Jeff
   through the same provider contract) against the deterministic judge on the
   **same extracted candidate evidence**;
4. measure required evidence retention, unknown/abstention behavior, context
   cost and downstream claim fidelity separately;
5. preserve the sealed S7 agent-repair corpus for broader generalization.

Only that fresh evidence can justify changing a default surface.
