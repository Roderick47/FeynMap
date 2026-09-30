# P2.4 — grounded behavioral evidence and task-conditioned relevance

P2.3b established a stricter boundary than the earlier delivery experiments:
choosing the right source file is insufficient, and even choosing the right
symbol is insufficient when the downstream packet omits the source behavior
that answers the task.  P2.4 adds a bounded behavioral layer **without
changing canonical semantic-graph truth or the legacy/default delivery path**.

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

The public composition surface is `TaskConditionedEvidencePipeline`.  Existing
`SparseContextPipeline` callers are unchanged.

## Truth and relevance are different responsibilities

The source analyzer decides what evidence exists.  A relevance judge decides
which already-grounded observations matter for the current task.  The judge
cannot:

- add a source observation;
- change a node/edge;
- increase an observation's evidence confidence;
- convert JavaScript heuristic evidence into supported static evidence;
- override an unresolved requested identifier;
- override behavior omitted by a critical evidence budget.

`DeterministicRelevanceJudge` is the reproducible baseline.  The optional
`JudgmentProviderRelevanceJudge` uses FeynMap's existing provider-neutral
`JudgmentProvider` contract.  The existing Jev adapter can therefore rank
relevance now; future Laya/Jeff-style adapters require no graph or P2.4 schema
change.  Provider failure falls back to the deterministic judge.

## Behavioral observations

`GroundedBehaviorExtractor` inspects only source spans for symbols already
selected by S3.  Each observation has a stable ID, selected-symbol ID, kind,
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

Python observations use AST-backed static evidence.  JavaScript/TypeScript
observations retain the existing conservative `javascript.source.*` evidence
semantics and therefore remain inferred rather than silently upgraded.

The envelope also derives compact structured facts from each exact witness:
reads, writes, literals, operators, call expressions, and transform chains.
For example, `item.quantity -= requested_quantity` records `item.quantity` as
both read and written; `.trim().toUpperCase()` retains both transforms.

## Ordering

The envelope records source order **within a symbol**.  This supports grounded
statements such as a validation call appearing before a mutation and a return.
It does not claim global runtime ordering, concurrency ordering, or dynamic
call ordering merely from source position.

## Tests and migrations are evidence channels, not noise

P2.4 applies the P2.1/P2.2 lesson one level deeper.  A generic relevance sort
can still let one evidence channel crowd out the causal path.  Before normal
packing, the behavioral packer reserves the strongest available witness for
each high-priority task dimension by evidence channel:

- ordinary implementation tasks reserve implementation behavior;
- test tasks reserve production behavior **and** test corroboration;
- migration tasks reserve migration behavior **and** relevant implementation /
  default behavior.

Remaining budget is spent essential → supporting → uncertain.  Explicitly
irrelevant observations are omitted.  Under uncertainty, FeynMap favors recall
rather than treating uncertain as false.

## Coverage and negative evidence

A selected symbol's complete source span is inspected by the supported local
extractor.  The model-facing envelope states the limit of that guarantee:

- local source scan: complete for the supported extractor;
- transitive runtime behavior: not claimed complete;
- dynamic dispatch: unknown unless separately evidenced;
- external side effects: unknown unless separately evidenced.

Therefore the absence of a refund call in a scanned local function can support
"no explicit refund operation appears in this body".  It cannot by itself
support "no refund can occur anywhere at runtime" when unresolved or external
callees remain.

The packet reports requested identifiers that were unresolved upstream,
critical behavior omitted by budget, supporting/uncertain evidence omitted by
budget, and call targets whose behavior is not present among selected symbols.
This preserves the project rule: **unknown is not false**.

## Budget discipline

`BehaviorEvidenceBudget` separately caps behavioral observations, inline source
witness characters, and the deterministic compact-JSON token estimate.  The
final envelope — including sequences, selection metadata, coverage/unknowns,
and sufficiency — is checked against the behavioral token cap.  If necessary,
lowest-value noncritical enrichment is removed first.  If an extremely small
budget cannot retain critical evidence, P2.4 drops evidence and marks the
packet insufficient rather than silently exceeding the cap.

The base S3 context estimate and P2.4 behavior estimate remain deterministic
`ceil(chars/4)` approximations, not vendor tokenizer/billing tokens.

## Sufficiency

The deterministic judge asks whether the selected behavioral dimensions are
enough for the task type.  Examples include conditions/raises for failure
questions, mutations for state-change questions, assertions for test
questions, returns/transforms for transformation questions, and calls/effects
for side-effect questions.

A learned provider may make a softer sufficiency judgment only after hard
source constraints pass.  It cannot overrule unresolved explicit identifiers
or missing critical behavior.

## Current evidence status

The original P2.3b fulfillment corpus is now a **development regression
fixture**.  P2.4 intentionally uses it to ensure the previously absent facts
become representable: validation-before-mutation, quantity decrement,
return construction, exception conditions, test assertions, migration guard
and default literal, cancellation status literals, and JavaScript normalization.
It must not be relabeled as a fresh held-out result.

Before making a new default/shipping claim, freeze a separate P2.4 downstream
corpus and answer oracle before inspecting its results.  The sealed S7
agent-repair corpus remains disjoint.

## Next measurements

1. Keep full Python 3.8/3.12 and recursive FeynMap CI green.
2. Replay the known P2.3b questions as development diagnostics and record
   behavioral evidence coverage/cost, without claiming independent accuracy.
3. Freeze a new P2.4 corpus before evaluating downstream answers.
4. Compare deterministic relevance with a provider-backed judge on identical
   extracted candidate evidence; measure retained required evidence, unknown /
   abstention quality, context cost, and downstream claim fidelity separately.
5. Only then consider whether task-conditioned behavioral delivery should
   become a default surface.
