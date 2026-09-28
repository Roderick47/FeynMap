# S6.6 — Native region-routing kernel

S6.6 implements the first real Rust computation in FeynMap while leaving the existing Python production router unchanged.

## Native implementation

The crate in native/routing_kernel/src/lib.rs now exports:

- NativeRegionIndex::new(...): copies and validates the nine static numeric arrays from S6.5.1.
- NativeRegionIndex.route(...): computes numeric region scores and bounded selected regions.
- region_count: read-only diagnostic property.
- abi_version() and implementation(): the existing extension/ABI identifiers.

The internal boundary stays feynmap.native_region_routing / 1.0.0. No public graph, snapshot or confidence contract was changed.

## Rust concepts introduced

**Struct and impl.** A struct is a typed container for the nine numeric arrays. impl attaches its constructor and methods. Vec<u32> stores contiguous unsigned indexes/offsets, while Vec<f64> stores 64-bit floating-point weights.

**Ownership and borrowing.** The PyO3 constructor converts the Python input into independently owned Rust Vec arrays. The route(&self, ...) method borrows those arrays immutably instead of taking ownership or modifying them. A native test proves that changing source Python lists after construction does not change native results.

**Result-based validation.** The constructor rejects malformed CSR offsets, unsorted/duplicate row indexes, out-of-range values, invalid numeric weights and oversized index tables. The route method rejects invalid query IDs, anchors and limits. Invalid inputs produce a Python ValueError through PyResult. No Rust unsafe feature is used.

**Two-pointer weighted intersection.** Both query token IDs and region token IDs are sorted. Rust advances two positions through these arrays, adding a token's IDF weight only on a match. This avoids repeated Python-level set lookup and generator overhead.

## Routing semantics preserved

The Rust implementation follows the S6.5.1 compact Python reference:

1. Unknown unique query terms still contribute to the normalized IDF denominator.
2. Low-weight symbolic regions are excluded except when they are the anchor.
3. Lexical and direct-path scores are normalized and weighted identically.
4. The anchor gets +2.0 locality; neighboring regions get +0.10.
5. Candidates are sorted by descending score, then ascending numeric region index. Numeric indexes were assigned in lexically sorted region-ID order.
6. General and direct-path selections alternate under the same bounded limit.
7. The anchor fallback and final aligned score vector are preserved.

## Validation

The optional tests/test_native_routing_integration.py suite verifies anchored/unanchored routing, empty/unknown terms, malformed inputs, independent array ownership and the six real FeynMap self-hosting queries.

Ordinary Python installations without the optional wheel skip the native-only suite. The native GitHub Actions workflow installs the compiled wheel and executes those tests under both Python 3.8 and Python 3.12, reusing the *same* cp38-abi3 wheel.

Full Python tests, recursive FeynMap self-analysis and the Python route benchmark remain independent regression gates.

## What S6.6 does not do

- Normal FeynMap continues to call its existing Python RegionIndex.route().
- There is no claim of a native performance improvement yet; S6.8 must measure the complete Python↔Rust call including query preparation/FFI overhead.
- S6.7 must expand differential conformance across harder independent/edge-case graphs.
- S6.9 can integrate an optional production native fast path only after correctness and measured performance have been accepted.

The native component is a deterministic accelerator beneath Python's semantic graph, never a competing source of graph truth.
