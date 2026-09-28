# S6.5.1 — Python ↔ Rust region-routing boundary

S6.5.1 defines the exact data boundary for the first Rust accelerator selected
in S6.4.3. It deliberately introduces **no Rust code**.

The goal is to make the later PyO3 implementation small, deterministic, and
easy to compare against Python.

## Mental model

Python remains responsible for semantic meaning:

```text
SemanticGraph
    |
    v
RegionIndex
    |
    | prepare once
    v
compact numeric routing index
    |
    | copy once across PyO3
    v
Rust NativeRegionIndex
    |
    | tiny request per query
    v
numeric selected regions + scores
    |
    v
Python maps indexes back to region IDs
    |
    v
RegionRouteResult
```

Rust is therefore a calculator underneath Python, not a second semantic engine.

## Why the boundary is numeric

Passing `SemanticNode`, Python dictionaries, sets, or nested objects into Rust
on every route call would force PyO3 to repeatedly inspect Python objects. That
would spend much of the saved CPU time crossing the language boundary.

Instead, Python converts the static region index once into:

- integer region indexes;
- integer token indexes;
- flat integer arrays;
- floating-point IDF/weight arrays.

Region names and token strings remain on the Python side. Rust returns numeric
indexes and Python converts them back to names.

This is both faster and safer because the native kernel cannot mutate the
canonical `SemanticGraph`.

## Ownership

Ownership is one of Rust's central ideas.

A value has a clear owner responsible for its lifetime. The future
`NativeRegionIndex` will **own** its copied arrays. Once constructed, a route
call does not need to borrow Python's graph or region objects.

Conceptually:

```text
Python                     Rust

RegionIndex
   |
   | one-time copy
   +---------------------> NativeRegionIndex
                              owns Vec<...>
                              owns Vec<...>
                              owns Vec<...>

query -------------------> route(...)
                           reads owned arrays
result <------------------ numeric indexes
```

Because routing is read-only after construction, the native object can later be
safe to call without mutating shared state.

## Static constructor boundary

`RoutingKernelData.native_constructor_args()` defines the one-time argument
order for the future PyO3 class.

The intended Rust storage is:

```text
region_weights             Vec<f64>
idf_by_token               Vec<f64>
unknown_token_idf          f64
region_term_offsets        Vec<u32>
region_term_ids            Vec<u32>
path_term_offsets          Vec<u32>
path_term_ids              Vec<u32>
adjacency_offsets          Vec<u32>
adjacency_region_indices   Vec<u32>
```

`u32` is sufficient for region/token indexes and keeps the representation
portable and compact. FeynMap would have to exceed billions of entries before
this index width became the limiting factor.

The Python reference currently stores ordinary Python integers. S6.5.2 will
perform checked conversion to the Rust integer types.

## CSR-style flat arrays

The region terms, path terms, and adjacency graph are represented with
**offsets + flat values**, often called a compressed sparse row (CSR) layout.

For example:

```text
region 0 tokens = [2, 7, 9]
region 1 tokens = [1, 4]

values  = [2, 7, 9, 1, 4]
offsets = [0, 3, 5]
```

To read region 0 Rust takes `values[0:3]`.
To read region 1 it takes `values[3:5]`.

This avoids a large tree of Python lists/sets and gives Rust contiguous memory
that CPUs can scan efficiently.

## Deterministic numbering

Python sorts region IDs lexically and assigns:

```text
region string -> region index
```

It also sorts the token vocabulary and assigns:

```text
token string -> token index
```

That has two benefits:

1. native tie-breaking can use region indexes and still match Python's lexical
   region-ID tie-break;
2. the native kernel does not need strings in its hot loop.

The boundary builder is deterministic and covered by tests.

## Query boundary

Each route call sends only:

```text
query_term_ids              Vec<u32>
unknown_query_term_count    u32
anchor_region_index         Option<u32>
limit                       u32
```

Python `None` maps naturally to Rust `Option<u32>`.

In Rust, `Option<T>` means the value is explicitly one of:

```text
Some(value)
None
```

This is safer than using a magic value such as `-1` to mean "no anchor".

## Why query tokenization stays in Python for v1

S6.4.3 initially identified tokenization as part of the routing cost. S6.5.1
intentionally keeps **canonical query tokenization** in Python for the first
native boundary.

Python's current tokenizer depends on Unicode `casefold()`, `isalnum()`, and
the existing stopword semantics. Reimplementing those immediately in Rust would
make the first port responsible for both acceleration *and* Unicode semantic
compatibility.

Instead:

- query text is tokenized once per route call in Python;
- tokens are mapped to integer IDs;
- unknown unique-token count is preserved because unknown terms contribute to
  the current IDF denominator;
- **path tokenization is moved out of the repeated hot loop entirely** and is
  prepared once in the static index.

If the remaining Python query-tokenization cost is still material after the
native scoring kernel lands, tokenizer acceleration can be measured as a
separate Rust candidate.

## Why unknown tokens are counted

Current routing computes the denominator from every unique query token,
including tokens that do not occur in any region.

If Rust received only known token IDs, a query containing an unknown word would
receive a different normalized score.

The request therefore includes:

```text
unknown_query_term_count
```

and the static index includes the IDF value for an unseen token. This preserves
the current Python scoring semantics.

## Native response boundary

The intended Rust result is:

```text
candidate_regions          u32
selected_region_indices    Vec<u32>
selected_scores            Vec<f64>
```

Python then maps numeric region indexes back to the original region IDs and
constructs the existing `RegionRouteResult`.

Rust never constructs FeynMap model objects.

## Floating point

Both implementations use 64-bit floating point (`f64` / Python `float`).

Tiny arithmetic differences between implementations may occur because of
operation ordering. Differential tests therefore require:

- exact selected region IDs and ordering;
- exact candidate count;
- score keys identical;
- scores equal within a small tolerance;
- no score difference may change ranking/selection.

## Python compact reference

`feynmap/rust_routing_boundary.py` includes a pure-Python implementation over
the compact numeric arrays.

It exists for one reason: before Rust is written, we can prove that the proposed
boundary contains enough information to reproduce `RegionIndex.route()`.

The tests cover:

- normal anchored routing;
- rare direct-path slot preservation;
- unknown query-token denominator behavior;
- low-weight symbol regions used as anchors;
- deterministic numeric table construction.

This compact Python implementation is a **conformance oracle**, not a new
production router.

## Internal ABI, not public substrate contract

The boundary is identified as:

```text
feynmap.native_region_routing / 1.0.0
```

This is an internal Python↔native ABI. It is **not** added to the frozen public
S6 substrate contract set.

That distinction matters:

- public substrate contracts protect external consumers;
- the native ABI protects the Python and Rust implementations from silently
  disagreeing with each other.

An incompatible internal boundary change should advance this ABI version and
update differential fixtures/tests, but it does not automatically require a
public semantic-graph version bump.

## No unsafe Rust required

Nothing in this design requires Rust's `unsafe` feature.

The future kernel can be written with ordinary safe Rust:

- owned `Vec<T>` arrays;
- checked indexes during construction;
- immutable reads during routing;
- ordinary sorting and arithmetic.

Rust's compiler then enforces memory ownership and lifetime rules for us.

That is a major reason Rust is attractive here: native speed without requiring
manual memory management like C/C++ for this kernel.

## Future PyO3 shape

S6.5.2 should expose approximately:

```text
NativeRegionIndex::new(static arrays...)

NativeRegionIndex.route(
    query_term_ids,
    unknown_query_term_count,
    anchor_region_index,
    limit,
) -> (
    candidate_regions,
    selected_region_indices,
    selected_scores,
)
```

The constructor is expensive relative to a route call but runs once per prepared
index. The route method should be small.

Because the Rust object owns only Rust memory during scoring, S6.5.2/S6.6 can
also evaluate releasing Python's Global Interpreter Lock while the native
kernel runs. That is a concurrency benefit, but it is not required for the
first correctness milestone.

## Acceptance of S6.5.1

This checkpoint is complete when:

- the compact representation is deterministic;
- it contains no canonical semantic objects in the native kernel data;
- the per-call request contains no region/token strings;
- the compact Python kernel reproduces existing route selection;
- the internal ABI is explicitly versioned;
- ordinary tests and recursive self-analysis remain green.

S6.5.2 may now add the PyO3/maturin project skeleton, but should still avoid
implementing routing behavior until the native build/import path is proven.
