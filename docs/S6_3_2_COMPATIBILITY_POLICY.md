# S6.3.2 — Substrate compatibility and versioning policy

This document defines how the S6 substrate contracts identified in
`S6_3_1_CONTRACT_INVENTORY.md` evolve. It is a policy checkpoint only:
S6.3.2 does not bump versions, change readers, or freeze contracts. S6.3.3 will
turn these rules into conformance fixtures; S6.3.4 will apply the freeze to the
accepted contract set.

## 1. Contract identity and version identity are separate

A portable FeynMap contract has:

- a stable **schema/contract identifier** such as
  `feynmap.semantic_graph` or `feynmap.repository_snapshot`;
- a semantic version `MAJOR.MINOR.PATCH`;
- optionally an exact **content digest** for one concrete declaration.

The schema identifier names a contract family. Renaming that identifier creates
a new contract family; it is not a minor or patch revision.

A content digest is an exact fingerprint, not a compatibility signal. Two
contracts may be semantically compatible while having different digests.

## 2. Semantic-version rules

### Major

Increment **MAJOR** when an existing consumer could interpret previously valid
data incorrectly, or when previously valid data is no longer valid.

Major changes include:

- removing or renaming an existing field;
- changing a field's type, units, nullability, requiredness, or meaning;
- changing the meaning of a previously defined enum value;
- adding a value to a **closed semantic vocabulary** where older readers cannot
  safely preserve its meaning;
- changing a default so omission has a different meaning;
- tightening validation so a previously valid payload becomes invalid;
- changing stable identity/hash semantics so unchanged source can receive
  different canonical node, edge, snapshot, graph, or contract identities;
- changing read-only/write or authorization semantics of a tool capability;
- adding a new required argument to an existing tool;
- removing or renaming an existing tool;
- changing an existing tool from one operation/meaning to another.

A major change requires an explicit migrator or a deliberate reader rejection.

### Minor

Increment **MINOR** for backward-compatible additive capability.

Minor changes include:

- adding an optional field whose absence retains the old meaning;
- adding an optional nested object or optional metadata;
- relaxing validation to allow additional values without changing existing
  values' meanings;
- adding a new independent grounding tool;
- adding an optional tool argument;
- adding new evidence/diagnostic metadata that does not change canonical truth;
- adding a new optional child record to a parent contract.

For the S6 frozen substrate, a minor release must continue to make all payloads
valid under the previous minor mean the same thing.

### Patch

Increment **PATCH** for corrections that do not change the accepted payload set
or contract semantics.

Patch changes include:

- documentation/description clarification;
- serializer or validator bug fixes that restore already-specified behavior;
- deterministic implementation fixes that preserve the same canonical
  identities and meanings.

A patch must not alter canonical IDs, hashes, contract digests for unchanged
declarations, required fields, valid enum meanings, or tool behavior.

## 3. Reader compatibility rules

Frozen S6 readers should apply the following order:

1. **Identifier:** require the expected schema/contract identifier.
2. **Major:** reject an unsupported major unless an explicit migration path
   exists.
3. **Minor:** within the same major, accept additive newer-minor fields only
   when the reader can safely ignore/preserve them under the rules below.
4. **Patch:** treat patch differences within a supported major/minor as
   compatible.

Current exact-version checks in Python remain implementation behavior until
S6.3.4. This policy is the target for the frozen cross-runtime contract, not a
claim that every current reader already implements it.

### Unknown fields

Within the same major:

- read-only consumers may ignore unknown optional fields;
- consumers that load and then re-emit a portable artifact must either preserve
  unknown fields losslessly or refuse to rewrite that newer payload;
- unknown fields must never change the interpretation of known required fields;
- producers must not use an unknown optional field to secretly override the
  meaning of an older field.

This rule prevents an older Python or Rust runtime from silently destroying
newer metadata when round-tripping an artifact.

### Unknown enum/vocabulary values

The canonical semantic vocabularies are **closed** for the frozen major:

- `NodeKind`
- `EdgeKind`
- `EvidenceKind`
- confidence-tier values when serialized as semantic truth

An unknown value in these vocabularies must be rejected rather than coerced to a
generic meaning. Adding a new semantic value therefore requires a major version
unless S6 later introduces and freezes an explicit extension-vocabulary
mechanism.

This is intentionally stricter than the legacy `feynmap.graph` v1 policy,
which permits additional legacy node/edge types with warnings.

## 4. Canonical semantic graph policy

`feynmap.semantic_graph` is the new substrate graph family.

Within one major version:

- node/edge IDs remain stable for unchanged semantic identity;
- existing node, edge, evidence, location, metadata fields keep their meaning;
- new optional metadata may be added;
- object key order is not semantic;
- node/edge collection order is not semantic graph truth, although producers
  should remain deterministic;
- canonical identity/hash logic must normalize any semantically unordered
  collections before hashing.

Changes to ID derivation, relationship meaning, evidence meaning, or closed
ontology values are major.

## 5. Analysis and confidence policy versions

`ANALYSIS_CONTRACT_VERSION` and `CONFIDENCE_POLICY_VERSION` describe
semantic policy, not merely JSON shape.

They use semantic versions, but callers may conservatively require **exact
version equality** for:

- incremental graph reuse;
- comparing confidence scores/tier outcomes;
- asserting that two snapshots were produced under equivalent analysis rules.

A minor policy version can describe additive analysis capability, but it does
not imply that cached analysis from an older minor is safe to reuse. Reuse
guards are intentionally stricter than wire-format readability.

## 6. Repository snapshot policy

`feynmap.repository_snapshot` owns snapshot identity and persistence metadata.

Within one major:

- new optional metadata may be added;
- nested file fingerprints inherit the snapshot major unless separately
  versioned later;
- `snapshot_id`, repository/content/graph hash meanings remain stable;
- `graph_schema_version` continues to identify the nested canonical graph
  contract independently.

A change that causes identical repository content + analysis inputs to receive a
different snapshot identity is major unless an independently versioned identity
algorithm is introduced first.

Parent compatibility does not override child compatibility: a readable snapshot
containing an unreadable graph major must still be rejected.

## 7. Grounding tool contract policy

`GROUNDING_TOOL_CONTRACT_VERSION` governs the transport-neutral grounding
catalog and its input declarations.

For an existing tool:

- add optional argument → minor;
- add required argument → major;
- remove/rename argument → major;
- narrow an accepted enum/range → major;
- widen an accepted range without changing existing meanings → minor;
- change read-only/effect semantics → major;
- semantic description clarification → patch when behavior is unchanged.

Catalog changes:

- add a new independent tool → minor;
- remove or rename a tool → major.

Tool capability digests remain exact declaration fingerprints and must change
when the fingerprinted declaration changes. Digest equality is stronger than
semantic-version compatibility; digest inequality alone does not mean
incompatibility.

Grounding **result** payloads are not frozen by this policy until they receive
versioned envelopes. A versioned input catalog must not be treated as implicitly
versioning every result dictionary.

## 8. Active state policy

`feynmap.active_state` is portable task state tied to an immutable snapshot.

Within one major:

- additive optional task-memory fields may be minor;
- nested retrieval-history rows inherit the active-state version;
- snapshot/reference semantics remain stable;
- changing the meaning of stored node/edge references is major;
- changing invalidation semantics so stale state could be accepted is major.

Runtime budgets, eviction strategy, reuse heuristics, and transition metrics are
implementation details and do not require active-state schema bumps unless they
change the serialized state meaning.

`feynmap.active_context` is not yet frozen. Before S6.3.4 it must either gain
a centralized versioned contract with conformance coverage or remain explicitly
outside the frozen set.

## 9. Tool-space policy

Freeze candidates:

- `feynmap.tool_capability`
- `feynmap.tool_capability_space`
- `feynmap.tool_schema_pack`

Compatibility is based on declared capability semantics, not routing scores.

For capability/schema-pack contracts:

- additive optional metadata → minor;
- changing tool identity, required input semantics, read-only semantics, or
  contract-digest canonicalization → major;
- delivered tool rows inherit the schema-pack version for their envelope while
  preserving the underlying tool contract version/digest.

`feynmap.tool_selection`, ranking scores, matched terms, margins, and adaptive
routing reasons remain internal and may change without substrate version bumps.

The capability-space envelope should receive its own version constant before it
is frozen; sharing the node schema version is an implementation shortcut, not a
long-term compatibility rule.

## 10. Unversioned external payloads

The S6.3.1 **needs-envelope** contracts are not eligible for freeze merely
because they are already returned by Python APIs.

Before becoming frozen cross-runtime contracts they must receive:

1. a stable identifier;
2. an explicit semantic version;
3. a documented required/optional field set;
4. clear nesting/version ownership;
5. reader behavior for unknown optional fields;
6. conformance fixtures.

This applies to:

- grounding result envelopes;
- model-facing minimal/sparse context;
- rehydrated active context;
- language-neutral integration-contract facts if exposed independently;
- judgment question/result wire payloads.

For minimal/sparse context specifically, the future frozen envelope should
separate **model-facing grounded facts** from algorithm diagnostics such as
packing iterations, routing scores, timings, and sufficiency reasons.

## 11. Integration-contract policy

`attributes.integration_contracts[]` affects canonical graph truth but is
currently an embedded extension structure.

Until it receives an independent contract:

- its existing fields are part of the semantic graph's attribute data, not an
  independently frozen wire ABI;
- changes that alter resulting canonical edges are governed by the analysis
  contract and semantic graph compatibility rules;
- diagnostic `metadata.integration` remains internal.

If integration contracts are later exposed as a first-class interchange format,
they need their own identifier/version rather than inheriting an undocumented
shape from node attributes.

## 12. Judgment-provider policy

The Python `JudgmentProvider` ABC is not a cross-runtime ABI.

If provider-neutral judgment becomes a frozen runtime boundary, S6 must freeze
the **wire protocol**, not Python class signatures. The wire envelope will need
an independent identifier/version and must define question kinds, answer
normalization, probabilities/confidence semantics, and error/abstention
behavior.

Until then, `JudgmentQuestion.to_wire()`, `JudgmentAnswer`, and
`JudgmentResult` remain provisional.

## 13. Legacy graph policy remains separate

`feynmap.graph` v1 keeps the compatibility guarantees already documented in
`GRAPH_SCHEMA.md`.

Its historical rule allowing new node/edge types as minor-version extensions
does **not** carry over to `feynmap.semantic_graph`. The two schema families
have independent version histories and compatibility policies.

No compatibility bridge may silently relabel one family as the other.
Conversion must be explicit.

## 14. Cross-runtime conformance expectations

S6.3.3 fixtures should test the policy, not Python implementation quirks.

At minimum, fixtures should prove:

- canonical serialization/deserialization preserves required semantic fields;
- same-major additive optional fields are readable without semantic changes;
- unsupported major versions are rejected;
- unknown closed semantic enum values are rejected;
- unknown optional fields are preserved by any round-tripping reference reader,
  or that reader refuses to rewrite them;
- canonical identity/hash fixtures agree across implementations;
- nested contract-version incompatibility is not hidden by a compatible parent;
- tool contract digests are deterministic;
- active state remains bound to the declared immutable snapshot.

Raw JSON object key order should not be used as a conformance requirement.
Exact canonical bytes are required only where the contract explicitly uses
canonical JSON to derive a digest/hash.

## 15. S6.3.2 decisions carried into S6.3.3/S6.3.4

The following decisions are now the compatibility target:

1. New S6 substrate contracts use semantic versions.
2. Schema identifiers are stable family identities.
3. Same-major field evolution is additive; requiredness/meaning changes are
   major.
4. Canonical semantic enums are closed; new meanings are major for now.
5. Unknown optional fields are safe for read-only use, but round-trip writers
   must preserve them or refuse the rewrite.
6. Identity/hash semantic changes are major.
7. Policy versions may use semver while cache/reuse guards remain exact.
8. Parent versions do not mask incompatible child versions.
9. Algorithm diagnostics stay internal.
10. Needs-envelope payloads remain provisional until explicitly versioned and
    covered by conformance fixtures.

S6.3.2 defines policy only. No current contract version is bumped or frozen by
this document.
