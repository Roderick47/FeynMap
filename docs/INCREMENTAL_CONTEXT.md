# Incremental analysis and stored snapshot context

Phase 2A now has two runtime optimizations over immutable repository snapshots:

1. conservative incremental refresh planning,
2. token-budgeted context retrieval from a stored graph.

Both are designed so performance optimizations cannot silently weaken FeynMap's evidence model.

## Incremental analysis contract

Incremental analysis is an optimization layer, not a second truth engine.

The current flow is:

```text
previous immutable snapshot
        ↓
current repository file inventory
        ↓
identity / analysis-contract / option checks
        ↓
changed-file delta
        ↓
conservative dependency closure
        ↓
┌───────────────────┬───────────────────────────────┐
│ no source changes │ changed / unsafe reuse case   │
│                   │                               │
│ reuse stored graph│ full FeynMapEngine fallback   │
└───────────────────┴───────────────────────────────┘
        ↓
new immutable snapshot + current pointer
```

### What is genuinely incremental today

When all of the following match:

- repository identity,
- analysis contract version,
- language/framework analysis options,
- repository file fingerprints,

FeynMap returns the previous semantic graph directly. `FeynMapEngine.analyze()` is not invoked.

This makes repeated AI/MCP queries and repeated snapshot checks inexpensive when the repository has not changed.

### Modified files

For modified files FeynMap computes a conservative file-level invalidation closure from stored semantic relationships including imports, calls, inheritance, dependencies, HTTP/integration relationships, reads/writes, persistence, queues and related edges.

The planner reports:

- directly changed files,
- impacted files,
- files that are candidates for reuse,
- whether a correctness fallback is required.

At this stage, changed repositories still use a full analysis fallback. FeynMap does **not** splice partially re-analyzed adapter fragments into an old graph until adapter-level fragment identity and merge semantics are proven.

This is deliberate. Reporting a useful invalidation closure is not permission to reuse stale facts.

### Added and removed files

File addition/removal forces a full rebuild because it can alter:

- language detection,
- framework detection,
- package/module topology,
- imports and re-exports,
- entry points,
- integration contracts.

### Analysis contract version

Every newly analyzed graph records:

```text
analysis_contract_version = 1.0.0
```

Incremental reuse requires an exact match with the current engine contract. A missing or changed version triggers a full rebuild even if source files are identical.

This is important for the future Rust-native implementation: Python and Rust can implement the same semantic contract and explicitly declare compatibility rather than assuming cache equivalence.

## CLI

Refresh from a previous snapshot:

```bash
feynmap incremental . --from <snapshot-id>
```

With explicit analysis selection:

```bash
feynmap incremental . \
  --from <snapshot-id> \
  --language python \
  --framework none
```

The response includes the new/current snapshot and an `IncrementalPlan` describing whether FeynMap reused, considered partial reuse, or fell back to a full rebuild.

## Stored snapshot context

`StoredSnapshotContext` loads a graph from `SnapshotStore` and never reads or reparses repository source.

It currently exposes reusable primitives for:

- repository summary,
- symbol inspection,
- relationship claim validation,
- token-budgeted context bundles,
- unresolved Python calls and unresolved integration contracts.

This class is intentionally transport-neutral. Phase 2B MCP should call this service (and related stored query services), not call `FeynMapEngine.analyze()` for every request.

## Token budget contract

A context bundle contains:

- immutable snapshot identity,
- the requested root symbol,
- nearby nodes ranked by graph distance and confidence,
- relationships between included nodes,
- compact evidence/provenance,
- explicit known/unknown grounding instructions,
- budget/truncation metadata.

Example:

```bash
feynmap stored-query <snapshot-id> FeynMapEngine.analyze \
  --kind context \
  --depth 2 \
  --max-tokens 4000
```

Repository summary without source parsing:

```bash
feynmap stored-query <snapshot-id> --kind summary
```

Unresolved/unknown surface:

```bash
feynmap stored-query <snapshot-id> --kind unresolved
```

The reference token estimator is deterministic and tokenizer-independent: serialized context length divided by four, rounded up. It is an approximate budgeting contract, not a claim about any particular LLM tokenizer. A future Rust implementation can reproduce the same behavior exactly or add an explicitly versioned exact-tokenizer mode.

The current evidence-bearing context format has a minimum supported budget of **512 approximate tokens**. Requests below that value are normalized to 512 and the response reports both `requested_max_tokens` and the effective `max_tokens`. This avoids pretending that required snapshot, symbol, grounding and budget metadata can fit into an arbitrarily small payload.

Relationships are trimmed before neighboring nodes. The root symbol and grounding semantics remain present. Final budget metadata reports the effective limit, estimated token count, included nodes/relationships, and whether truncation occurred.

## Remaining incremental work

The next performance step is true changed-file reuse:

1. define stable adapter fragment identities,
2. let language adapters parse selected files into deterministic fragments,
3. invalidate dependent fragments using the stored closure,
4. merge new and reused fragments,
5. rerun framework and integration enrichment globally where required,
6. compare the result against a full rebuild in conformance tests,
7. retain full-rebuild fallback whenever equivalence cannot be proven.

That work is an optimization. The stored snapshot/context contract is already sufficient to begin the Phase 2B MCP transport over correct full graphs.
