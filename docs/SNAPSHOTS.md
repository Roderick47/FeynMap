# Repository snapshots and persistence

Phase 2A changes FeynMap from an analyzer that must rebuild a graph for every consumer into a system that can analyze once and query a stored, verified repository snapshot many times.

## Why snapshots come before MCP

An MCP server should not parse the entire repository every time an AI asks `find_callers`, `semantic_diff`, or `validate_claim`.

The intended flow is:

```text
repository
    ↓
FeynMapEngine.analyze()
    ↓
clone-independent SemanticGraph
    ↓
capture repository identity + file inventory
    ↓
immutable RepositorySnapshot
    ↓
SQLite SnapshotStore
    ↓
current snapshot pointer
    ↓
query / diff / context / MCP requests
```

MCP therefore becomes a query surface over a known snapshot rather than a hidden source-code reparsing loop.

## CLI

Capture and persist the current repository graph:

```bash
feynmap snapshot .
```

The default store is:

```text
.feynmap/snapshots.sqlite
```

Language and framework selection are part of snapshot identity:

```bash
feynmap snapshot . --language python --framework none
```

A custom store can be supplied:

```bash
feynmap snapshot . --store /path/to/feynmap-snapshots.sqlite
```

Compare two already-stored snapshots without reparsing either historical state:

```bash
feynmap diff <before-snapshot-id> <after-snapshot-id>
```

or with an explicit store:

```bash
feynmap diff <before> <after> --store /path/to/feynmap-snapshots.sqlite
```

## Snapshot identity

A `RepositorySnapshot` records:

- `snapshot_id`
- `repository_key`
- canonical repository locator
- local `root_hint`
- Git revision when available
- sorted file/content inventory
- repository content hash
- semantic graph hash
- semantic graph schema version
- analysis options
- creation timestamp

The immutable `snapshot_id` is derived from:

```text
snapshot schema version
+ repository_key
+ Git revision
+ repository content hash
+ semantic graph hash
+ semantic graph schema version
+ analysis options
```

Creation time, local checkout path, and SQLite store path are deliberately excluded from semantic identity.

## Clone-independent repository identity

The semantic graph uses a canonical repository root:

```text
id             repository:root
qualified_name repository
root           .
```

The absolute checkout path is retained only in `RepositorySnapshot.root_hint` for local navigation. It is not embedded in the canonical graph.

Git repository locators are normalized to a transport-neutral host/path form. For example:

```text
https://github.com/acme/project.git
ssh://git@github.com/acme/project.git
git@github.com:acme/project.git
```

normalize to the same logical locator:

```text
git:github.com/acme/project
```

Embedded HTTP credentials and SSH user names are therefore not part of repository identity.

With the same canonical Git origin, revision, source contents, and analysis options, two clones in different filesystem directories are expected to produce the same:

- semantic graph payload,
- `repository_key`,
- `content_hash`,
- `graph_hash`,
- `snapshot_id`.

Their `root_hint` values may differ, as intended.

Repositories without a usable Git origin fall back to a local `path:` locator. Those snapshots are intentionally checkout-local because there is no stronger repository identity available.

## Repository content inventory

Every normal repository file is fingerprinted using SHA-256 over its bytes. Generated/cache directories are excluded, including:

- `.git`
- virtual environments
- `node_modules`
- Python caches
- `.feynmap`

The sorted fingerprint list produces the repository `content_hash`. The `.feynmap/` directory is excluded so saving a snapshot cannot change the content hash of the repository it describes.

## Graph serialization

`SemanticGraph` supports lossless reconstruction with `SemanticGraph.from_dict()`.

Deserialization restores:

- node/edge enum types,
- source locations,
- evidence objects,
- attributes and metadata,
- graph indices,
- diagnostics.

Schema and schema-version mismatches are rejected rather than silently accepted. Adapter diagnostics are preserved and merged with structural validation diagnostics.

## Immutable store

`SnapshotStore` uses Python's standard-library SQLite support as the current reference implementation.

The `snapshots` table stores immutable snapshot metadata, file inventory and serialized graph. Saving a known snapshot ID with different content is rejected as an immutable-ID collision.

A separate `current_snapshots` table maps each `repository_key` to the snapshot that normal queries should currently use.

```text
immutable history
    snapshot A
    snapshot B
    snapshot C
         ↑
         │
current pointer
```

Moving the current pointer does not mutate historical snapshots. Stored graphs are hash-verified when loaded.

SQLite is an implementation choice, not the cross-runtime contract. The versioned graph/snapshot JSON structures and their semantics are the portability boundary for future storage backends and the planned Rust-native FeynMap implementation.

## Snapshot diffs

FeynMap now separates two kinds of change.

### File inventory delta

`diff_file_inventories()` reports:

- added files,
- removed files,
- modified files,
- unchanged count.

### Semantic graph delta

`diff_graphs()` reports:

- added/removed/changed semantic nodes,
- added/removed/changed relationships.

Node identity uses stable semantic node IDs. Relationship identity uses:

```text
(source node, edge kind, target node)
```

rather than the generated edge ID, because evidence locations or detector details may change while the semantic relationship remains the same.

`diff_snapshots()` combines the file and semantic deltas and rejects comparisons between different repositories.

This provides the foundation for:

- self-hosting before/after quality measurement,
- incremental invalidation,
- change-impact explanations,
- MCP `semantic_diff`,
- coding-agent review of what a patch actually changed in the architecture.

## Security / privacy

Git HTTP(S) remote userinfo such as embedded credentials or tokens is removed before repository identity is stored or hashed. SSH user names are likewise transport details and are not retained in canonical Git repository locators.

The local checkout path remains available only as `root_hint` so local tools can navigate source files.

## Next steps

The next Phase 2A work builds on the stored/diffable graph:

1. use file-inventory deltas to drive incremental analysis,
2. define conservative invalidation rules and a full-rebuild fallback,
3. build token-budgeted context primitives over a stored snapshot,
4. expose current/specified snapshots through the Phase 2B MCP grounding service.
