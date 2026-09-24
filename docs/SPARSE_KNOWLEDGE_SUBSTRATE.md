# Sparse Knowledge Activation Substrate

## Product realignment

FeynMap is evolving from "a semantic map exposed to AI" into a **sparse
knowledge-activation and context-control substrate**.

The semantic graph remains the source of truth. The new substrate decides what
small grounded portion of that graph should be active for the current task,
how deeply it should be explored, when retrieval is sufficient, and how little
context can be delivered without losing answer quality.

The product boundary becomes:

```text
repository / files / runtime evidence
              ↓
      canonical semantic graph
              ↓
   sparse knowledge activation
              ↓
      minimal sufficient context
              ↓
     LLM / agent / IDE / MCP / API
```

MCP, HTTP APIs, IDE integrations, and agent adapters are transports and
consumers of the substrate. They are no longer the architectural destination.

## Where FeynMap is now

The current codebase already has most of the correctness foundation that this
vision needs:

- a language-neutral evidence-backed semantic graph;
- deterministic Python, HTML, JavaScript, and framework analysis;
- cross-language and cross-runtime relationship resolution;
- immutable repository snapshots and semantic diffs;
- token-budgeted stored context primitives;
- explicit evidence and uncertainty semantics;
- provider-neutral judgment contracts with JEV integration;
- JEV-guided concept and node-specific graph search with bounded depth, beam,
  node budgets, deterministic fallback, and an inspectable search trace;
- context-ranking and repair experiments that already test compact state,
  relevance, recall, and token budgets.

PR #28 is especially important: JEV now acts as a **search policy over grounded
FeynMap truth**, rather than merely reranking an already retrieved list.

## Where the previous roadmap was heading

The previous roadmap treated the grounding service and MCP integration as the
next major destination, followed by richer language coverage, repair
benchmarks, multi-source truth, and a later Rust implementation.

Those remain useful, but the priority changes:

1. the **substrate hot path** becomes the product core;
2. MCP/API/IDE become thin delivery surfaces;
3. language adapters continue to improve the graph, but should not delay
   retrieval-efficiency work;
4. expensive LLM/JEV analysis must become conditional, not mandatory;
5. Rust becomes a latency/throughput implementation target after the substrate
   contracts and benchmark semantics stabilize.

## New design principle

> Keep enormous grounded knowledge available while activating only the minimum
> subset required for the current task.

This mirrors a broader efficiency pattern seen in modern open model
architectures: sparse MoE activates only a small subset of model capacity,
sparse attention selects only a small subset of context, hybrid attention keeps
cheap state and performs expensive exact retrieval only when needed, and agent
systems retain large histories while only a fraction should remain relevant to
the next step.

FeynMap applies the same principle **outside the model** to external knowledge.

## V1 hot path

The target hot path is:

```text
query
  ↓
cheap query/task state
  ↓
region / summary routing
  ↓
JEV or deterministic sparse activation
  ↓
local graph retrieval
  ↓
sufficiency + confidence cutoff
  ↓
minimal context packing
  ↓
downstream model
```

The normal hot path should not require an LLM call. An expensive judgment or
LLM stage is reserved for ambiguity, conflicting evidence, low confidence, or
tasks that explicitly request deeper analysis.

## Architectural responsibilities

### Canonical graph

Owns truth: nodes, relationships, provenance, uncertainty, snapshots, diffs,
and language/framework/runtime semantics.

### Routing/index layer

Owns cheap narrowing: repository/domain regions, summaries/clusters,
lexical/structural seeds, reusable active working sets, and cached query/task
state.

### Activation policy

Owns what deserves deeper work: deterministic policy when sufficient,
JEV-guided policy when useful, bounded traversal, adaptive effort, and early
stopping. The policy may rank or select grounded candidates. It must not invent
graph facts or silently rewrite evidence confidence.

### Sufficiency layer

Owns the decision to stop: coverage of required concepts, unresolved critical
relationships, contradictions, marginal information gain, and confidence that
additional traversal is unlikely to materially improve the context package.

### Context packer

Owns downstream payload size: the minimal evidence-preserving node/edge set,
token budget, evidence references, unresolved facts, and optional task-specific
summaries.

## First-class metrics

FeynMap should optimize and report candidate touch ratio, knowledge activation
ratio, context compression ratio, quality retention, routing latency, and
downstream token/cost savings.

The initial feynmap.activation module deliberately starts with only the metrics
that can already be measured from GuidedSearchResult without changing retrieval
behavior.

## Realigned implementation sequence

### S0 — Observe before optimizing

- [x] Preserve graph truth and evidence semantics.
- [x] Preserve snapshot/context primitives.
- [x] Preserve JEV-guided bounded search from PR #28.
- [x] Add explicit candidate-touch and knowledge-activation metrics.
- [ ] Record baseline activation metrics on FeynMap and a larger real codebase.
- [ ] Add routing-latency instrumentation.

### S1 — Hierarchical/region activation

- [ ] Build stable repository region summaries/indexes.
- [ ] Route to regions before individual nodes.
- [ ] Compare flat search vs region-first search for recall, activation ratio,
      and latency.
- [ ] Keep deterministic region routing available without JEV.

### S2 — Adaptive sufficiency

- [ ] Define a provider-neutral sufficiency result.
- [ ] Stop search when coverage/confidence is adequate.
- [ ] Track marginal information gain per search expansion.
- [ ] Escalate deterministic → JEV → optional LLM only when required.

### S3 — Minimal sufficient context

- [x] Add an explicit final context-selection stage after activation.
- [x] Preserve evidence endpoints/relationships together.
- [x] Optimize quality retained per delivered token.
- [x] Benchmark quality retention against the same model-facing activated payload.

### S4 — Active working state

- [ ] Reuse query/task graph regions across multi-step agent/tool loops.
- [x] Distinguish persistent graph memory from active context.
- [x] Invalidate/re-expand the working set when new evidence changes the task.

### S5 — Tool and agent routing

- [ ] Represent tool capabilities as grounded routable nodes/contracts.
- [ ] Select small tool subsets before exposing schemas to an LLM.
- [ ] Apply the same activation metrics to tool-space routing.

### S6 — Performance substrate

- [ ] Cache only where measurement shows value.
- [ ] Reduce network/service hops.
- [ ] Benchmark the Python hot path first.
- [ ] Freeze substrate contracts.
- [ ] Port latency-critical components to Rust where profiling justifies it.

## What is deliberately not being thrown away

The realignment keeps language neutrality, evidence/confidence semantics,
snapshots, incremental analysis, context selection, JEV/provider-neutral
judgments, difficult parser/relationship examples, repair evaluation, MCP
contracts, and multi-source truth. They become supporting layers around the
substrate rather than separate product directions.

## Immediate benchmark question

> How much of a large real repository can FeynMap avoid touching while
> preserving the same essential retrieval/repair quality?

That is the first concrete test of the new product thesis.


## S0/S1 benchmark record — 24 September 2026

The first substrate benchmark uses FeynMap self-hosting plus five pinned
Wikonomi V2 tasks from the earlier v1F context-ranking experiment. Wikonomi
tasks are checked out at their original pre-fix revisions so retrieval is not
scored against files that moved later. Files created by the repair itself are
reported as unretrievable/new-file gold and excluded from retrieval recall.

Latest accepted S1 run: GitHub Actions `substrate-baseline` run 35947449021.

| Repository | Strategy | Candidate touch | Knowledge activation | Routing | Active context | Essential recall |
|---|---|---:|---:|---:|---:|---:|
| FeynMap | flat | 7.38% | 1.94% | 7.1 ms | 3,859 tokens | 100% |
| FeynMap | region hybrid | 8.02% | 2.09% | 10.2 ms | 4,066 tokens | 100% |
| Wikonomi v1F | flat | 9.09% | 0.93% | 8.8 ms | 2,395 tokens | 85% |
| Wikonomi v1F | region hybrid | 9.41% | 1.32% | 18.6 ms | 3,324 tokens | **100%** |

Timing is a CI reference measurement, not a production latency guarantee.

### Decisions from S1

**Keep:**

- local evidence-backed semantic traversal as the primary hot path;
- query-aware deterministic routing when no judgment provider is present;
- edge priority for application boundaries such as `RENDERS`, `EXTENDS`,
  `LOADS`, requests and invocations;
- semantic path-continuity scoring across multiple hops;
- a small global region channel as an escape hatch for knowledge outside the
  local search horizon;
- one representative activation per selected region;
- explicit diagnostics separating extraction, graph reachability and pruning
  failures.

**Reject:**

- hard region filtering before graph search: it reduced candidate touch but
  collapsed recall on Wikonomi;
- treating repository-root containment as a semantic traversal path: it turns
  the ownership root into a high-degree shortcut and adds noise;
- scoring a repair-created file as a retrieval miss when that file did not
  exist in the pre-fix tree.

### Next optimization target

S1 establishes a high-recall path, but the region channel is still always-on.
S2 should add provider-neutral **sufficiency and adaptive escalation**:

```text
local sparse traversal
        ↓
sufficient?
  yes ──┴──→ pack context
  no
  ↓
region activation
        ↓
sufficient?
  yes ──┴──→ pack context
  no
  ↓
JEV / optional expensive judgment
```

The target is to retain the S1 100% benchmark recall while moving average
latency/context cost closer to the flat-search path.


## S2 adaptive sufficiency contract

S2 introduces a separate provider-neutral effort controller. It does not change
graph truth and it does not use benchmark gold labels at task time.

The deterministic decision sequence is:

```text
local semantic traversal
        ↓
cheap region summaries only
        ↓
sufficiency(local)
   ┌────┴────┐
  yes        no
   │          │
 stop     activate bounded
           region reps
              ↓
       sufficiency(merged)
          ┌───┴───┐
         yes      no
          │        │
        stop   JEV/provider
                 if available
```

The first provider-neutral sufficiency signals are:

- **query coverage** — how much of the task vocabulary is represented by the
  activated grounded nodes;
- **novel region gain** — whether cheap unopened region summaries contain query
  terms that the active set does not yet explain;
- **region coverage** — how much of the cheap routed region set is already
  represented locally;
- **marginal gain** — how much new task vocabulary the most recent search depth
  added;
- **frontier pressure** — how much candidate information the fixed sparse beam
  had to leave unopened.

These are routing/effort signals, not epistemic truth scores. A sufficient
result means "additional retrieval is unlikely to add task-relevant grounded
context", not "the downstream answer is guaranteed correct".

Every adaptive result records the stop stage (`local`, `region`, or `jev`),
the escalation sequence, all sufficiency signals, uncovered query terms, and
the specific reason(s) for escalation.


## S2 benchmark outcome — 24 September 2026

S2 is evaluated recursively on FeynMap itself and on the same five pinned
Wikonomi v1F tasks used for S1. A new self-hosting task begins at
`AdaptiveSparseSearch.from_node` and requires FeynMap to recover its own
sufficiency and routing implementation.

Accepted reference: GitHub Actions `substrate-baseline` run **35958839100**.

| Repository | Strategy | Candidate touch | Knowledge activation | Routing | Active context | Essential recall | Adaptive decisions |
|---|---|---:|---:|---:|---:|---:|---|
| FeynMap | flat | 7.13% | 1.91% | 7.26 ms | 3,913 tokens | 100% (5/5) | — |
| FeynMap | always-on region | 7.75% | 2.14% | 9.32 ms | 4,247 tokens | 100% (5/5) | — |
| FeynMap | **adaptive** | **7.13%** | **1.91%** | **8.57 ms** | **3,913 tokens** | **100% (5/5)** | **5 local / 0 region** |
| Wikonomi v1F | flat | 9.09% | 0.93% | 10.02 ms | 2,395 tokens | 85% (3/5) | — |
| Wikonomi v1F | always-on region | 9.41% | 1.32% | 13.96 ms | 3,324 tokens | 100% (5/5) | — |
| Wikonomi v1F | **adaptive** | **9.16%** | **1.08%** | **12.76 ms** | **2,762 tokens** | **100% (5/5)** | **3 local / 2 region** |

CI latency is comparative evidence, not a production SLA. In this run adaptive
Wikonomi retrieval used about **17% fewer active-context tokens** than the
always-on S1 hybrid while preserving its full recall, and it was about **8.6%
faster** on the same runner.

### Accepted S2 policy

The effort controller now makes a provider-neutral three-way decision:

```text
local grounded search
        ↓
local precheck
   ┌────┼─────────────┐
 strong │ uncertain   │ clearly insufficient
   ↓    ↓             ↓
 FAST   cheap route   route + region activation
 stop      ↓                   ↓
        full sufficiency      NORMAL
          ┌──┴──┐              ↓
        stop   region      still insufficient
                            + provider available
                                  ↓
                                DEEP
                         judgment provider / JEV
```

The precheck can conclude either **sufficient**, **insufficient**, or
**uncertain**. Strong grounded coverage stops without constructing a global
route. Low grounded coverage combined with stalled marginal information gain
escalates directly. Only ambiguous cases pay for the fuller route-aware
sufficiency calculation.

Task vocabulary is graph-grounded and IDF-weighted. Ordinary prose that does
not occur in the substrate is not treated as missing knowledge. Region novelty
is computed from the representative nodes that would actually be activated,
rather than from every token in an entire file.

The runtime exposes effort as:

- **fast** — local grounded search only; no global route/provider;
- **normal** — bounded deterministic region activation when local evidence is
  insufficient;
- **deep** — a configured judgment provider only after deterministic local and
  region stages remain insufficient.

These are selected by evidence/sufficiency, not by a user-facing fixed mode.

### Rejected S2 policies

- Raw query-word coverage: it treated prose such as “the”, “should”, and
  “people” as missing repository knowledge and escalated almost everything.
- Any-novel-region-term escalation: preserved recall but sent all five
  Wikonomi tasks through the expensive path.
- Rarity alone: reduced context substantially but falsely stopped on the
  map-history task (95% mean recall).
- Re-evaluating sufficiency after region activation when no further provider
  exists: it could not change the action and only added latency.

The accepted policy combines **rare repository-specific novelty** with
**low-coverage + stalled marginal gain**, plus the direct local fast path.


## S3 benchmark outcome — 24 September 2026

S3 treats the S2 activated graph as input and minimizes only the downstream
model-facing payload. It preserves activation roots, critical evidence,
relationship endpoints, parent/boundary continuations, source-file diversity,
multi-concept witnesses, and direct cross-file orchestration dependencies.
The packer grows its token budget only until activation-derived critical
evidence is retained.

Accepted reference: GitHub Actions `substrate-baseline` run **35962742536** at
`9781fcb0`.

| Repository | Activated model-facing context | S3 delivered context | Compression | Essential recall |
|---|---:|---:|---:|---:|
| FeynMap | ~7,661 tokens | ~2,948 tokens | ~61.5% | 100% (6/6) |
| Wikonomi v1F | ~6,313 tokens | ~2,686 tokens | ~57.4% | 100% (5/5) |

The activated/delivered comparison uses the same model-facing payload
representation, not debug metadata.

## S4 active-state foundation — 25 September 2026

S4 introduces a separate portable working-state contract. Persistent graph
truth stays in the immutable snapshot. The agent carries only stable references
to the currently relevant nodes, edges, and regions plus bounded task memory
(concepts, open questions, contradictions, and a small retrieval history).

`ActiveStateRuntime` can rehydrate those references into exact canonical
node/relationship evidence when the model needs it. Multi-step transitions
retain a bounded connected subset of prior state, add newly activated S2/S3
evidence, and drop stale peripheral references rather than appending every
previous context package forever.

A state is snapshot-bound. If repository evidence changes to a different
snapshot, reuse is rejected and the task must re-expand from canonical truth.
Explicit invalidation is also available for evidence changes that make the
current working assumptions stale.

The remaining S4 optimization is to feed retained regions back into routing so
repeated tool/agent steps can avoid redundant global routing, then benchmark
cumulative context growth avoided over realistic long-horizon tasks.
