# S6.7 — Differential Python/Rust routing conformance

S6.7 validates the optional compiled NativeRegionIndex before any production
fast-path integration. Python remains the semantic authority, and the existing
RegionIndex.route() is still the normal production implementation.

## What differential conformance means

Every accepted request is evaluated three ways:

1. The original high-level Python RegionIndex.route().
2. The S6.5.1 compact numeric Python reference.
3. The compiled PyO3 NativeRegionIndex.route() method.

Both Python implementations and Rust must agree on anchor region, candidate
count, exact ordered selected region IDs, exact score-map keys and scores within
an absolute and relative tolerance of 1e-12. The compiled Rust method is also
called twice for every request to prove deterministic repeated output.

## Independently authored oracle

tests/fixtures/contracts/s6_7_routing_oracles.json explicitly specifies expected
outcomes without generating the expectations from Python or Rust. This prevents
two implementations from passing by agreeing on the same wrong assumption.

The 12 requests cover an empty graph, empty query, lexical score ties and
lexical tie-breaking, a tight region budget, direct-path bonuses, unknown
tokens, a forced anchor without lexical match, empty-query neighbor locality,
a symbolic low-weight region with and without an anchor, and Unicode casefolding.

## Seeded independent graphs

feynmap/rust_routing_conformance.py constructs graph sizes of 1, 37 and
513 nodes from a fixed local random seed (677007), then executes 36 requests
per graph. These cover a range of anchors, limits, empty/stopword/unknown
queries, token combinations, path weights, symbolic regions and adjacency.

The corpus totals 108 deterministic synthetic requests. A fixed generator
seed makes regressions reproducible; this is not a statistical accuracy claim.

## Recursive self-hosting

The harness analyzes the checked-out FeynMap repository, constructs the region
index once, then routes the six real tasks already specified by
experiments/rust_region_routing_s6.json through all three implementations.

## Acceptance counts

- Independently expected oracle requests: 12.
- Seeded stress requests: 108.
- Real FeynMap self-hosting requests: 6.
- Total: 126 three-way comparison requests per interpreter version.

GitHub Actions builds a single Python-3.8 abi3 native wheel, installs it on
Python 3.8 and reuses the exact same wheel under Python 3.12. Both run the full
conformance harness and publish separate JSON report artifacts:

- s6-7-native-conformance-py38
- s6-7-native-conformance-py312

The report includes the ABI version, corpus counts, seed, actual region counts,
score tolerance and pass/fail status. The CLI also emits a failure report with
the case context and traceback if a comparison fails.

Run locally after installing the native companion wheel:

    python -m feynmap.rust_routing_conformance --repo-root . --output performance-results/s6-7-conformance.json

## Valid-input domain and validation convergence

S6.7 also tests malformed CSR tables, numeric weights, out-of-range token or
region IDs, duplicate/unsorted IDs, invalid anchors and limits, and the empty
index. It revealed that Python and Rust originally rejected the same multiply
invalid offset array but checked its violations in different orders. Rust
now checks offset monotonicity before the final offset, matching Python.

The Python reference validator was hardened to make its domain agree with
Rust: nonfinite/negative region weights, nonfinite/nonpositive IDF values,
unsorted/duplicate CSR rows and values outside the native u32 width are
rejected. Values too large to convert into Rust u32 can raise OverflowError
at the PyO3 conversion boundary; both implementations reject them rather than
treating them as valid routing requests.

These changes align an internal native ABI, not a public semantic graph or
snapshot contract.

## Conformance vs performance

S6.7 has established strict equivalence for the specified finite corpus,
not a mathematical proof for all possible graphs and floats. More independent
fixtures can be added as new failure modes are discovered.

The conformance corpus does not measure production speed. In particular,
the normal FeynMap router has not been switched to Rust and the existing
Python routing benchmark remains the stable pre-acceleration baseline.

S6.8 must separately measure the full Python-to-Rust path on the same runners,
including one-time numeric index preparation, native construction, Python
query tokenization, FFI overhead, native scoring and response materialization.
Only a demonstrated net improvement and unchanged retrieval quality can
justify an optional production fast path in S6.9.

## Development assets

- feynmap/rust_routing_conformance.py — reproducible three-way harness/report.
- tests/fixtures/contracts/s6_7_routing_oracles.json — independent answer key.
- tests/test_rust_routing_conformance_spec.py — oracle/seeded Python-only gate.
- tests/test_rust_routing_validation.py — Python ABI invalid-input gate.
- tests/test_native_routing_integration.py — native invalid-input and smoke gates.
- .github/workflows/rust-native-build.yml — native Py3.8/Py3.12 conformance.

S6.7 is complete only when both native versions and both ordinary Python
versions pass alongside recursive self-analysis.
