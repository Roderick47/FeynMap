# S6.3.4 — Frozen substrate contract set

S6.3.4 closes the first FeynMap substrate contract-freeze checkpoint.

The freeze is deliberately narrow. It covers only portable surfaces that have
an explicit version, a defined compatibility policy, and conformance coverage.
It does **not** freeze every Python result object or every dictionary currently
returned by the implementation.

## Machine-readable declaration

The accepted set is declared in:

```text
feynmap/contracts.py
```

through `FROZEN_SUBSTRATE_CONTRACTS` and
`frozen_contract_manifest()`.

The declaration itself uses:

```text
schema:         feynmap.substrate_contract_set
schema_version: 1.0.0
```

## Frozen contracts

| Contract | Identifier | Frozen version | Role |
|---|---|---:|---|
| Canonical semantic graph | `feynmap.semantic_graph` | `1.0.0` | Cross-runtime repository truth |
| Analysis contract | policy version | `1.2.0` | Analysis-semantic equivalence / incremental guard |
| Confidence policy | policy version | `2.0.0` | Evidence/confidence interpretation |
| Repository snapshot | `feynmap.repository_snapshot` | `1.0.0` | Immutable persistence/identity |
| Grounding tool catalog | catalog version | `2.1.0` | Transport-neutral read-only tool inputs |
| Active state | `feynmap.active_state` | `1.0.0` | Portable bounded task state |
| Tool capability | `feynmap.tool_capability` | `1.0.0` | Grounded routable tool contract |
| Tool capability space | `feynmap.tool_capability_space` | `1.0.0` | Portable capability catalog |
| Tool schema pack | `feynmap.tool_schema_pack` | `1.0.0` | Bounded model-facing tool delivery |

The semantic ontology (`NodeKind`, `EdgeKind`, `EvidenceKind`, serialized
confidence tiers) is governed by the semantic-graph contract and the closed
vocabulary rules in `S6_3_2_COMPATIBILITY_POLICY.md`.

Nested file fingerprints inherit the repository-snapshot contract. Active
retrieval history inherits the active-state contract. Delivered tool rows
inherit the tool-schema-pack envelope while carrying their underlying grounding
contract version and exact digest.

## Explicitly not frozen

The following remain provisional:

- grounding result envelopes;
- minimal-context results;
- sparse-context results;
- rehydrated `feynmap.active_context`;
- a first-class integration-contract wire format;
- the judgment-provider wire protocol.

They may continue to evolve without claiming frozen cross-runtime compatibility.
Before promotion they need a stable identifier/version, field semantics,
reader behavior, and conformance fixtures.

Algorithm outputs remain internal, including region/search scores, sufficiency
diagnostics, adaptive effort/reasons, tool-selection scores/matched terms,
timings, active transition metrics, cache layout, SQLite layout, and concrete
Python class structure.

## Legacy graph remains separate

`feynmap.graph` v1 remains a legacy-stable compatibility family.

It is **not** relabelled as `feynmap.semantic_graph`, and its version history
is not merged with the canonical substrate graph. Any conversion between the
families must remain explicit.

## Freeze evidence

The freeze is backed by:

- `docs/S6_3_1_CONTRACT_INVENTORY.md`;
- `docs/S6_3_2_COMPATIBILITY_POLICY.md`;
- `tests/fixtures/contracts/s6_contracts_v1.json`;
- `tests/test_contract_conformance.py`;
- `tests/test_frozen_contracts.py`;
- the recursive FeynMap self-analysis CI gate.

The conformance fixture pins deterministic graph/snapshot/tool identity vectors
so another implementation, including a future Rust implementation, can prove it
agrees with the Python reference where canonical hashing/digests are contract
semantics.

## Change discipline after freeze

A frozen version is not immutable forever. It means changes must follow the
S6.3.2 compatibility policy.

In particular:

- breaking semantic changes require a major version;
- additive compatible fields/capabilities require a minor version;
- non-semantic corrections may use a patch;
- exact identity/digest changes require explicit compatibility review;
- analysis/confidence policy changes may invalidate caches even when their wire
  formats remain readable;
- provisional surfaces must not be added to the frozen set without new
  conformance coverage.

The test suite pins the current accepted versions. A version change therefore
requires an intentional test/fixture/policy update rather than accidental drift.

## Recursive-development relationship

Contract work now follows `docs/RECURSIVE_DEVELOPMENT.md`.

The current FeynMap implementation analyzes the FeynMap repository in CI on
every push/pull request through the `recursive-self-check` job. A contract
change must therefore preserve both ordinary conformance tests and FeynMap's
own grounded architecture invariants.

S6.3 is complete after this checkpoint. The next performance phase may consider
Rust only where profiling justifies it, using these frozen contracts as the
cross-runtime boundary.
