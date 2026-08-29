# Phase 2B MCP grounding service

Phase 2B exposes FeynMap's immutable, evidence-backed semantic snapshots to AI clients through the Model Context Protocol (MCP).

The first rule of this phase is architectural:

```text
MCP transport
      ↓
GroundingService
      ↓
StoredSnapshotContext / FeynMapQuery / semantic diff
      ↓
immutable SnapshotStore
```

The MCP layer must not become a second analysis engine. Tool calls should query already-grounded semantic state and preserve the same known / inferred / unknown semantics used everywhere else in FeynMap.

## Current groundwork

`feynmap.grounding` defines a transport-neutral, read-only application layer before any MCP SDK is introduced.

It contains:

- `GroundingTool`
- `GROUNDING_TOOLS`
- `GROUNDING_TOOL_CONTRACT_VERSION`
- `GroundingService`

Each tool has a deterministic JSON Schema 2020-12 input contract. The service returns normal JSON-compatible dictionaries and has no dependency on an MCP transport, web framework, LLM vendor, or authentication provider.

This boundary is intentional because the same contracts should later be callable through:

- local MCP over stdio,
- remote MCP over HTTP,
- a normal HTTP API,
- Python library calls,
- a future Rust-native FeynMap implementation.

## Initial grounding tool surface

The current service-level tools are:

| Tool | Purpose |
| --- | --- |
| `repository_summary` | Snapshot identity, graph size, languages/frameworks, diagnostics and evidence coverage |
| `get_symbol` | One symbol plus direct incoming/outgoing relationships |
| `find_callers` | Stored incoming/caller closure |
| `find_dependencies` | Stored outgoing/dependency closure |
| `change_impact` | Evidence-backed impact/caller closure |
| `validate_claim` | Check whether a relationship is supported by stored evidence |
| `trace_path` | Find one bounded evidenced path between two symbols |
| `find_integrations` | Return integration/boundary relationships |
| `explain_evidence` | Show evidence attached to a symbol and its direct relationships |
| `unresolved` | Surface unresolved calls/contracts so clients preserve uncertainty |
| `context_bundle` | Deterministic token-budgeted grounding context |
| `semantic_diff` | Compare two stored snapshots without reparsing historical source |

These are application contracts, not yet registered MCP tools.

## MCP protocol target

The initial transport implementation should target the current MCP protocol revision:

```text
2026-07-28
```

The modern protocol is stateless at the core. For a FeynMap remote grounding service this is a useful fit because a request can identify the repository/snapshot it wants and any service replica can answer from shared persisted state.

The official transports relevant to FeynMap are:

### 1. stdio — local/private deployment

The MCP client launches the FeynMap MCP server as a local child process and communicates over standard input/output.

This is the best first transport because:

- no public server is required,
- no domain is required,
- no TLS certificate is required,
- no hosting bill is required,
- repository source and SQLite snapshots can remain on the developer's machine,
- it is ideal for testing the tool contracts with coding agents before remote deployment.

### 2. Streamable HTTP — remote deployment

A remote FeynMap MCP service can later expose an `/mcp` endpoint through ordinary web infrastructure.

This is when hosting, authentication and shared storage decisions matter.

There is no special piece of hardware called an "MCP server" that must be purchased. A remote MCP server is an application deployed to normal compute such as a container/PaaS/VM/serverless environment that supports the selected MCP SDK/runtime.

## Python runtime decision before transport work

FeynMap currently declares:

```text
Python >= 3.8
```

The current official MCP Python SDK v2 requires:

```text
Python >= 3.10
```

Therefore this groundwork deliberately does **not** add the `mcp` dependency yet.

Before the actual MCP transport is implemented we should choose one of these packaging strategies:

### Option A — raise FeynMap's Python floor to 3.10+

Simplest package/runtime structure, but drops Python 3.8/3.9 support for the whole project.

### Option B — keep FeynMap core on Python 3.8+ and make MCP an optional 3.10+ component

For example, the semantic core remains broadly compatible while a `feynmap-mcp` executable/extra runs under a newer interpreter.

This is the preferred near-term design unless maintaining two runtime floors creates excessive packaging complexity.

### Option C — defer the production MCP transport to the future Rust-native service

This best matches the long-term performance target, but delays a working MCP integration unnecessarily. The Python reference implementation is useful for freezing and testing the protocol/tool contracts first.

## What is needed from the project owner before remote deployment

Nothing needs to be purchased for the local stdio MCP stage.

Before a **remote** MCP deployment, decisions/input will be needed on:

1. **Audience** — private use only, selected developers/partners, or public SaaS/API.
2. **Repository ingestion model** — analyze repositories locally and upload snapshots, let the server clone repositories, connect directly to GitHub, or support more than one mode.
3. **Authentication** — who may call the remote service and which repositories/snapshots each identity may access.
4. **Hosting** — preferred provider and monthly budget. Ordinary application hosting is sufficient; no MCP-specific server purchase is required.
5. **Domain** — whether the service should live under a dedicated hostname such as an API/MCP subdomain.
6. **Persistence** — whether SQLite is sufficient for the first single-instance deployment or whether shared Postgres/object storage is needed immediately.
7. **Python packaging decision** — whole-project Python 3.10+, optional MCP component, or another deployment split.
8. **Usage/privacy policy** — especially whether source code is allowed to leave a developer machine when remote analysis is enabled.

Those choices should be made before implementing authentication and remote Streamable HTTP, not before the local groundwork.

## Security boundary

The initial grounding surface is intentionally read-only.

A grounding MCP server should not edit repositories, execute arbitrary commands, or infer relationships that are absent from the semantic graph. Future mutation tools, if any, should be a separate capability with separate authorization.

For a remote deployment, repository/snapshot identifiers must also be authorization-scoped. Knowing a snapshot ID must never be sufficient by itself to read another tenant's code model.

## Next implementation step — deliberately deferred

After this groundwork is reviewed, the first actual MCP transport should be a small local stdio adapter that:

1. uses the official MCP SDK,
2. registers the versioned `GROUNDING_TOOLS` catalog,
3. validates tool arguments using the corresponding schemas/types,
4. dispatches directly to `GroundingService.call()`,
5. returns structured tool results without reparsing source,
6. has protocol-level conformance tests,
7. does not add remote hosting/auth complexity yet.

Only after local MCP behavior is correct should Phase 2B proceed to Streamable HTTP, authentication, multi-user repository access and production hosting.
