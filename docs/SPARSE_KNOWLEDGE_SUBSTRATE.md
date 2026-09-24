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

- [ ] Add an explicit final context-selection stage after activation.
- [ ] Preserve evidence endpoints/relationships together.
- [ ] Optimize quality retained per delivered token.
- [ ] Benchmark downstream quality against full context and baseline RAG.

### S4 — Active working state

- [ ] Reuse query/task graph regions across multi-step agent/tool loops.
- [ ] Distinguish persistent graph memory from active context.
- [ ] Invalidate/re-expand the working set when new evidence changes the task.

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
