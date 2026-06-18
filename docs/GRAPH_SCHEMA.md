# FeynMap Graph Schema

FeynMap graph artifacts use the stable schema identifier:

```text
feynmap.graph
```

The current schema version is:

```text
1.0.0
```

The machine-readable JSON Schema is available at `docs/graph-schema-v1.json`.

## Versioning policy

FeynMap follows semantic versioning for graph artifacts:

- **Major** versions may remove fields or change their meaning.
- **Minor** versions may add optional fields, node types, edge types, or metadata.
- **Patch** versions clarify validation or fix serialization without changing meaning.

Consumers should reject unsupported future major versions rather than guessing.
Unversioned historical graphs are treated as version `0.0.0` and migrated into v1.

## Top-level contract

```json
{
  "schema": "feynmap.graph",
  "schema_version": "1.0.0",
  "generator": {
    "name": "FeynMap",
    "version": "2.0.0"
  },
  "graph": {
    "directed": true,
    "multigraph": true,
    "node_count": 2,
    "edge_count": 1
  },
  "nodes": [],
  "edges": [],
  "diagnostics": {
    "valid": true,
    "errors": [],
    "warnings": [],
    "error_count": 0,
    "warning_count": 0
  },
  "extensions": {}
}
```

The `nodes` and `edges` arrays remain at the top level for compatibility with
older FeynMap consumers.

## Node contract

Every node contains:

- `id`: globally unique stable identity.
- `name`: human-readable local name.
- `qualified_name`: module- or scope-qualified name.
- `type`: semantic graph role.
- `language`: source language or `null`.
- `file`: compatibility alias for the source file.
- `source`: normalized file and line span.
- `metadata`: FeynMap metrics and analysis metadata.
- `attributes`: extension fields not defined by the core schema.
- `line_start` and `line_end`: compatibility aliases retained in schema v1.

New framework-specific values must be placed in `attributes` unless promoted by
a future schema version.

## Edge contract

Every edge contains:

- `id`: deterministic identity derived from source, type, and target unless supplied.
- `source`: source node ID.
- `target`: target node ID.
- `type`: dependency relationship type.
- `confidence`: number from 0 to 1, or `null` when not measured.
- `evidence`: human-readable evidence strings.
- `attributes`: extension fields.
- `resolution`: compatibility field for resolver strategy.
- `line`: compatibility field for source line evidence.

Edge IDs are deterministic, making graph diffs and caches stable across repeated
analysis of unchanged code.

## Validation

```python
from feynmap import validate_graph

diagnostics = validate_graph(graph)
if not diagnostics["valid"]:
    print(diagnostics["errors"])
```

Strict validation raises `GraphSchemaError`:

```python
from feynmap import validate_graph

validate_graph(graph, strict=True)
```

Validation checks:

- node and edge array types;
- non-empty identities;
- duplicate node and edge IDs;
- edge source and target references;
- confidence bounds;
- source-location structure;
- registered node and edge types.

Unknown types are preserved and reported as warnings so minor-version extension
remains possible.

## Normalization and migration

```python
from feynmap import normalize_graph

v1_graph = normalize_graph(legacy_graph)
```

Normalization is idempotent. Running it repeatedly produces the same graph.
Historical unversioned output is migrated as schema `0.0.0` into v1.

Compatibility can be checked before processing an artifact:

```python
from feynmap import schema_compatibility

result = schema_compatibility(graph.get("schema_version", "0.0.0"))
if not result["compatible"]:
    raise RuntimeError("Unsupported graph schema")
```

## Compatibility guarantees for v1

Within schema major version 1:

- Existing required fields will not be removed.
- Existing field meanings will not be changed.
- New optional metadata may be added.
- New node or edge types may be introduced with validation warnings in older v1 readers.
- Unknown extension fields remain preserved under `attributes` or `extensions`.
