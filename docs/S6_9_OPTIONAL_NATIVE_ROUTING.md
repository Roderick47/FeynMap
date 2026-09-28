# S6.9 — Optional Rust production routing with Python fallback

## Integration decision

Rust is integrated into the ordinary RegionIndex.route() entrypoint, but
remains OFF BY DEFAULT. The original Python router is the fallback and
reference algorithm. The optional acceleration is suitable for sustained
repeated region queries on a long-lived index; the measured self-hosting
end-to-end workflows did not demonstrate a meaningful whole-workflow speedup.

## How to opt in

Install FeynMap's ordinary Python package. To enable native routing, install
the optional feynmap-native-routing companion wheel built by the
rust-native-build GitHub Actions workflow for the target platform.

Set FEYNMAP_NATIVE_ROUTING=1 before starting a process, or explicitly create:

    index = RegionIndex(graph, native_routing=True)

An explicit native_routing=False overrides an environment opt-in for that
individual index. Existing RegionIndex(graph) calls remain Python-only unless
the environment flag has been set.

An optional diagnostic flag FEYNMAP_NATIVE_ROUTING_VERIFY=1 performs each
selected native route again through the original Python reference and
compares anchor/candidate count, ordered selected IDs, score keys and scores
within 1e-12. It falls back to Python if they disagree. This flag incurs
Python routing cost and is therefore intended for verification, not for
performance testing.

## Why the native index is lazy and owned by RegionIndex

A RegionIndex captures a single SemanticGraph snapshot. A native index is
only prepared on the FIRST route call that actually needs it, then reused
for subsequent calls by that RegionIndex. No native cache is shared globally
between repositories or snapshots. A lock serializes the one-time setup
when concurrent agent calls share the same index.

Adaptive search can decide that local evidence is already sufficient and
never call RegionIndex.route(); such a task allocates NO native routing index
even when the environment opt-in flag is set. That behavior was confirmed
in the recursive self-hosting benchmark.

## Failure behavior

- Wheel absent: Python fallback, and no repeated wheel-load attempts.
- Unsupported internal ABI: Python fallback, never construct the native index.
- Constructor or malformed-index failure: Python fallback.
- Runtime native exception: disable native for this index, return the
  current query's normal Python route, then use Python for later queries.
- Optional verification mismatch: disable native for this index and use
  Python for the affected query and later queries.

Native failure is contained per RegionIndex rather than changing a process-
wide default. Other index instances are not affected.

Per-instance index.native_routing_stats exposes requested/status/setup
attempts/successful native route calls/fallback count and failure type for
instrumentation without mutating graph truth.

## Native validation

Ordinary Python CI includes opt-in/default, lazy singleton construction,
explicit override, unavailable wheel, mismatched ABI, native runtime error,
shadow-verification mismatch, parallel first-use and per-index reuse tests.
The compiled PyO3 extension also continues to pass S6.7's 126 three-way
differential cases on Python 3.8 and 3.12, plus S6.8's full route benchmark.

## S6.9 full-workflow benchmark methodology

feynmap/rust_routing_workflow.py analyzes the checked-out FeynMap repository
once, then uses that same semantic graph for five paired runs of each
routing mode: original Python versus opt-in Rust. Execution order alternates
to reduce first/second measurement bias.

Both representative workflows process the same six self-hosting tasks:

- region-first search + minimal context (region routing necessarily used);
- adaptive sparse search + minimal context (may stop before region routing).

Each measurement INCLUDES all RegionIndex construction, native lazy setup,
search and context packing. The common initial repository parse/graph analysis
is measured but excluded from paired timing. The runner compares selected
regions, activated and delivered node IDs, token counts, essential recall,
adaptive stage/effort/escalations and route scores. Silent fallback fails
native-workflow acceptance.

Predeclared no-material-regression gate for a workflow that uses the native
accelerator: native median <= 1.15 times the Python median. When adaptive
search never invokes region routing, equivalence and zero native setup are
required; its timing ratio is informational only.

## First GitHub Actions result

Workflow run 36423099435, functional head a5b78520, Linux x86-64,
Python 3.12.14, five pairs per strategy:

| Six-task workflow | Python median | Opt-in Rust median | Ratio | Native calls and setup |
|---|---:|---:|---:|---|
| Region-first + minimal context | 612.729 ms | 615.602 ms | 1.00469 (0.99533x speed) | 6 routes; 1 setup; 0 fallbacks |
| Adaptive + minimal context | 500.839 ms | 505.160 ms | 1.00863 (0.99145x speed) | 0 routes; 0 setups; 0 fallbacks |

All six tasks maintained full essential recall under both strategies and
both routing modes. Selected regions, activated/delivered node IDs and context
token counts remained identical between Python and the opt-in route.

The region-first native path passes the <=15% whole-workflow regression gate.
The slight observed timing differences are not compelling evidence of a real
application speed gain or loss, especially for the adaptive workflow where
the Rust implementation was not invoked.

## Interpreting S6.8 versus S6.9

S6.8 established roughly 22-24x speedup for a reused isolated route,
including Python query preparation, FFI and materialization, with native
index setup amortized at approximately eight route calls.

The present region-first workflow uses only six routes per newly constructed
index. Its one-time native setup largely offsets that routing speedup. The
adaptive self-hosting workload bypasses routing entirely thanks to local
sufficiency. These observations reinforce the decision to retain Python as
the default rather than advertising a full FeynMap 20x performance gain.

## Release policy and future work

S6.9 completes an optional, safe production entrypoint; it does not enable
Rust by default or combine the wheel with the root setuptools package.
Native build/import, conformance and full workflow checks run through
rust-native-build. The full report is preserved as the s6-9-full-workflow
Actions artifact.

Reconsider a default native mode only if real user/agent telemetry shows
long-lived indexes performing enough routes to recover the extra setup,
and repeated realistic end-to-end benchmarks demonstrate a meaningful
whole-workflow improvement. Keep the Python reference available in all cases.
