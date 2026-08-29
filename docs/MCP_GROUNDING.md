# Phase 2B MCP grounding service

Phase 2B exposes FeynMap's immutable, evidence-backed semantic snapshots to AI clients through the Model Context Protocol (MCP).

The architectural rule is:

```text
MCP transport
      ↓
GroundingService
      ↓
StoredSnapshotContext / FeynMapQuery / semantic diff
      ↓
immutable SnapshotStore
```

The MCP layer is not a second analysis engine. Tool calls query already-grounded semantic state and preserve the same known / inferred / unknown semantics used everywhere else in FeynMap.

## Runtime split

FeynMap deliberately has two Python runtime floors:

```text
FeynMap semantic core      Python >= 3.8
optional MCP component     Python >= 3.10
```

The core package keeps `requires-python = ">=3.8"`.

The optional extra is:

```bash
pip install "feynmap[mcp]"
```

and installs the official MCP Python SDK v2 only when the interpreter is Python 3.10+.

The MCP entry point is separate:

```text
feynmap       -> core analysis/query/snapshot CLI
feynmap-mcp   -> optional local MCP server
```

`feynmap.mcp_server` imports the MCP SDK lazily. Importing or using the FeynMap semantic core on Python 3.8/3.9 therefore does not import MCP.

If `feynmap-mcp` is launched on an unsupported runtime, it exits with an explicit message rather than changing the core runtime requirement.

This split also preserves a clean boundary for the future Rust-native MCP/API implementation.

## Grounding service

`feynmap.grounding` defines the transport-neutral read-only application layer.

It contains:

- `GroundingTool`
- `GROUNDING_TOOLS`
- `GROUNDING_TOOL_CONTRACT_VERSION`
- `GroundingService`

Each grounding operation has a deterministic JSON Schema 2020-12 contract. The service returns JSON-compatible dictionaries and has no dependency on an MCP transport, web framework, LLM vendor, or authentication provider.

The same application contracts can therefore be called through:

- local MCP over stdio,
- future remote MCP over Streamable HTTP,
- a normal HTTP API,
- Python library calls,
- a future Rust-native FeynMap implementation.

## MCP tool surface

The local MCP server exposes:

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

All tools are declared read-only to MCP clients and operate on a closed stored semantic graph. Tool annotations are advisory metadata, not a security boundary; the implementation itself is read-only.

## Local stdio workflow

The first actual transport is stdio.

In stdio mode the MCP host launches `feynmap-mcp` as a child process. JSON-RPC flows through stdin/stdout. No TCP port, public server, domain, TLS certificate, or hosting account is required.

### 1. Create a snapshot

From the repository you want FeynMap to serve:

```bash
feynmap snapshot /absolute/path/to/repository
```

This creates or updates:

```text
/absolute/path/to/repository/.feynmap/snapshots.sqlite
```

and marks the new semantic snapshot as current.

### 2. Install the optional MCP component

Use Python 3.10+:

```bash
pip install "feynmap[mcp]"
```

For a local editable checkout:

```bash
pip install -e ".[mcp]"
```

### 3. Launch the server

Serve the repository's current snapshot:

```bash
feynmap-mcp --project /absolute/path/to/repository
```

The process intentionally prints nothing to stdout because stdout is the MCP protocol wire.

Pin an immutable historical snapshot instead:

```bash
feynmap-mcp \
  --project /absolute/path/to/repository \
  --snapshot <snapshot-id>
```

Use an explicit store when it is not under the repository:

```bash
feynmap-mcp \
  --project /absolute/path/to/repository \
  --store /absolute/path/to/snapshots.sqlite
```

You can also select the current snapshot for an explicit repository key:

```bash
feynmap-mcp --store /path/to/snapshots.sqlite --repository-key <repository-key>
```

## Important snapshot behavior

The MCP server binds to one selected semantic snapshot when the process starts.

It does **not**:

- run `FeynMapEngine.analyze()` during a tool call,
- silently change snapshots halfway through a session,
- edit source code,
- execute arbitrary repository commands.

This makes one MCP process reproducible. To move to a newly created current snapshot, restart the local MCP process.

`semantic_diff` may read two other immutable snapshots from the same configured store, but it still never reparses historical source.

## MCP protocol target

The implementation uses the official MCP Python SDK v2, which targets the current MCP protocol line and supports modern `2026-07-28` connections while negotiating compatibility where supported by the SDK.

For the local server, stdio is the transport. The official SDK owns protocol framing and lifecycle behavior; FeynMap owns only the grounding operations behind it.

Protocol-level tests use the SDK's in-memory `Client(server)` transport. That tests real MCP tool discovery, schema generation, dispatch, structured output, and error handling without needing a network server or subprocess.

## Host configuration shape

Exact configuration files differ between MCP hosts, but the local launch contract is intentionally simple:

```text
command: feynmap-mcp
args:    --project /absolute/path/to/repository
```

A generic host configuration therefore looks conceptually like:

```json
{
  "mcpServers": {
    "feynmap": {
      "command": "feynmap-mcp",
      "args": ["--project", "/absolute/path/to/repository"]
    }
  }
}
```

Use the host's current documented configuration format when connecting a real client; do not assume every host uses the same JSON keys.

## Local security model

The initial MCP surface is read-only.

The stdio process can read the configured SQLite snapshot store. It does not need repository write permissions for grounding queries, although `--project` may read local Git metadata to identify the repository's current snapshot pointer.

For maximum reproducibility/minimum filesystem dependency, launch it with both an explicit `--store` and `--snapshot`.

A local MCP host should launch the executable directly rather than through a shell string when possible.

## Testing strategy

The normal test matrix requests `.[dev,mcp]` on Python 3.8 and 3.12.

- On Python 3.8, the environment marker does not install the MCP SDK. Core compatibility and MCP-boundary tests still run.
- On Python 3.12, the SDK is installed and protocol tests use the official in-memory MCP client.

The protocol test verifies that the server lists the expected grounding tools and that real MCP calls reach stored snapshot operations such as repository summary, symbol lookup, claim validation, and context bundles.

This does not replace testing against real MCP hosts. Host interoperability remains the next local validation step.

## Remote Streamable HTTP — deliberately deferred

Remote MCP is not implemented in this stage.

A future remote FeynMap MCP service can expose a Streamable HTTP endpoint through ordinary application hosting. That is when hosting, authentication, authorization, shared persistence and multi-user isolation become required design decisions.

There is no special piece of hardware called an "MCP server" that must be purchased. A remote MCP server is an application deployed to normal compute such as a container/PaaS/VM environment.

## What is needed from the project owner before remote deployment

Nothing needs to be purchased for the local stdio MCP stage.

Before remote deployment, decisions/input will be needed on:

1. **Audience** — private use only, selected developers/partners, or public SaaS/API.
2. **Repository ingestion model** — local analysis + uploaded snapshots, server-side Git cloning, direct GitHub integration, or multiple modes.
3. **Authentication** — who may call the service and which repositories/snapshots each identity may access.
4. **Hosting** — preferred provider and monthly budget.
5. **Domain** — whether the service should have a dedicated API/MCP hostname.
6. **Persistence** — SQLite for a single-instance experiment versus shared Postgres/object storage for multiple replicas/users.
7. **Usage/privacy policy** — especially whether source code or semantic snapshots may leave a developer machine.
8. **Operational targets** — expected repositories, repository sizes, users, concurrency, latency and availability.

Those choices should be made before implementing remote authentication and Streamable HTTP, not before local stdio testing.

## Next Phase 2B step

The next step is not to buy hosting. It is to connect `feynmap-mcp` to one or more real MCP hosts/clients and verify interoperability using a real FeynMap snapshot.

After local interoperability is proven, we can decide whether to:

1. deepen the local MCP experience first,
2. build the remote Streamable HTTP adapter,
3. improve semantic coverage/language adapters before remote deployment,
4. or begin planning the Rust-native implementation boundary.
