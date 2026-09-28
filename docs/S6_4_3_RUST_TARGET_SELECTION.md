# S6.4.3 — First Rust target selection

S6.4.3 selects exactly one first Rust acceleration target and defines the
benchmark that will decide whether the port is worth keeping.

No Rust implementation is introduced in this checkpoint.

## Selected target

The first Rust target is the deterministic lexical scoring kernel inside:

```text
feynmap.routing.RegionIndex.route()
```

This function receives a query plus an already-built region index and chooses a
small ordered set of relevant repository regions.

It performs repeated:

- query/path tokenization;
- set-membership checks;
- IDF-weighted lexical accumulation;
- locality weighting;
- candidate sorting and bounded selection.

S6.5.1 deliberately narrows the first native ABI: Python retains canonical
query tokenization, while path terms are prepared once and Rust receives only
numeric query/token IDs for scoring and selection. Tokenization can be moved
later only if a fresh profile justifies it.

These are mechanical operations. They do not make JEV/model judgments and they
do not alter canonical graph truth.

## Why this target is suitable for Rust

Rust is a compiled systems language. For this target, the important property is
that the scoring loop can execute as native machine code over compact data
structures instead of repeatedly entering the Python interpreter for generator,
string, set and float operations.

Rust is **not** being introduced because it understands code better than
Python. Python remains the semantic reference and orchestration layer.

The intended relationship is:

```text
Python semantic graph / policy
          |
          v
   prepared region index
          |
          v
Rust deterministic scoring kernel
          |
          v
selected region IDs + scores
          |
          v
Python continues adaptive search/JEV/context work
```

The Rust component will therefore be an accelerator, not a second source of
semantic truth.

## Profile evidence

The latest functional substrate profile used for this decision is the
post-S6.3/adversarial-resolution head `22df5c2b`. Subsequent consolidation
commits before this checkpoint changed documentation/branch bookkeeping rather
than the routing implementation.

For the self-hosting adaptive/minimal workload:

- total profiled elapsed: about **6.15 s**;
- `feynmap/routing.py`: about **0.259 s internal time**, the largest FeynMap
  module by internal time in that run;
- routing token-generation generator: about **0.167 s internal time** across
  roughly **510k calls**;
- `routing._tokens`: about **0.398 s cumulative time**;
- the workload analyzed about **2,026 nodes / 6,814 edges**.

This is exactly the pattern where a native loop can help: a large number of
small deterministic operations rather than a small number of expensive model
calls.

## Candidates considered but deferred

### Minimal-context packing

`minimal_context.py` was close to routing in internal profile time. It is not
the first Rust target because packing still mixes:

- selection policy;
- token-budget growth;
- compact payload construction;
- Python dictionaries and evidence objects;
- a provisional model-facing result envelope.

It is less isolated than region scoring and is more likely to evolve.

### Python AST indexing

`python_source.ast_index()` has substantial cumulative cost, but Python AST
objects are CPython-specific structures. Passing or reproducing them across a
Rust boundary would create a much more complicated first FFI interface and
would make the first accelerator Python-language-specific.

That is a poor first demonstration of FeynMap's language-neutral substrate.

### Tool-space scoring

Tool routing is deterministic and Rust-friendly, but after the S6.2 cache work
its absolute cost is small. The latest tool-routing benchmark completed 25
iterations in about **0.51 s**, with `tool_space.py` around **0.129 s**
internal time. It does not currently justify being the first native port.

## What is *not* being ported

The first Rust checkpoint does not port:

- `SemanticGraph`;
- adapters or framework detection;
- JEV/provider calls;
- adaptive sufficiency;
- minimal-context policy;
- active-state policy;
- grounding/tool-routing policy;
- model-facing result composition.

This keeps FeynMap's reasoning and fast-changing policy in Python.

## Benchmark

The Python reference benchmark is:

```text
python -m feynmap.rust_routing_benchmark \
  experiments/rust_region_routing_s6.json \
  . \
  --output performance-results/rust-region-routing-python.json
```

The workload:

- analyzes FeynMap once;
- constructs `RegionIndex` once;
- resolves six representative self-hosting tasks;
- performs 10 warm-up rounds;
- performs 200 measured rounds;
- therefore measures 1,200 `RegionIndex.route()` calls;
- records exact route signatures separately from timing.

The benchmark deliberately excludes repository analysis and index construction
from the route timing. Otherwise a fast routing kernel could be hidden by work
that is not part of the first Rust port.

## Initial Python reference baseline

The first GitHub Actions run of the new route-only benchmark produced:

| Metric | Python reference |
|---|---:|
| Graph nodes | 2,038 |
| Graph edges | 6,857 |
| Regions | 308 |
| Region-index build | 102.510 ms |
| Measured route calls | 1,200 |
| Route elapsed | 1,694.872 ms |
| Mean route | 1,412.393 us |
| Throughput | 708.018 routes/s |

The index-build number is recorded for context but is **not** part of the first
Rust speedup target. The selected port is the repeated route kernel after the
index exists.

The numbers are runner-specific. Acceptance compares Python and Rust on the
same benchmark/runner and uses repeated-run medians rather than treating this
single baseline as a universal latency claim.

## Correctness requirements for the future Rust implementation

For the same graph, query, anchor and limit, Rust must match the Python
reference on:

1. anchor region;
2. candidate-region count;
3. ordered selected-region IDs;
4. score-map keys;
5. route scores within a small floating-point tolerance;
6. deterministic repeated output.

Selected regions must match exactly. Floating-point score comparison may allow
tiny implementation-level differences, but no such difference may change
ordering or selected output.

The existing region-routing unit fixtures remain semantic guardrails, including
rare direct-path preservation and disconnected relevant-region activation.

## Performance acceptance target

The first Rust port should not be accepted merely because it works.

S6.8 should require, on the same runner/workload:

- at least **2.0x route-only throughput** versus the Python reference when
  comparing a median of repeated benchmark runs;
- exact selected-region equivalence;
- no loss of essential-context recall in the established self-hosting
  activation benchmark;
- no material regression in full adaptive/minimal routing latency;
- Python fallback remains available.

If the native boundary overhead prevents a meaningful route-only speedup, the
Rust experiment should be rejected or the boundary redesigned rather than
forcing Rust into production.

## Benchmark assets

S6.4.3 adds:

- `feynmap/rust_routing_benchmark.py`;
- `experiments/rust_region_routing_s6.json`;
- `tests/test_rust_routing_benchmark.py`;
- `.github/workflows/rust-routing-benchmark.yml`.

The workflow currently measures the Python reference. S6.6/S6.7 will add the
Rust implementation and differential result to the same benchmark family.

## Next checkpoint

S6.5.1 should define the Python↔Rust data boundary for this kernel.

The key design question is how to represent region terms, document frequency,
path terms, adjacency/locality, query tokens and scores without passing rich
Python objects into Rust.

No PyO3/maturin code should be written until that boundary is explicit.
