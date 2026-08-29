# FeynMap V3 Architecture

## Goal

FeynMap V3 turns the project from a Python-framework analyzer into reusable semantic infrastructure for software engineering and AI agents.

The canonical product is **one evidence-backed model of the whole software system**, even when that system contains multiple languages, frameworks, processes and protocols.

The architecture separates:

1. source-language parsing,
2. framework interpretation,
3. repository-level graph composition,
4. cross-language/cross-runtime integration resolution,
5. canonical software semantics,
6. querying and AI grounding,
7. downstream applications such as migration.

## Canonical semantic core

The canonical graph lives under `feynmap/core/` and must not import Django, Flask, FastAPI, Python AST machinery, JavaScript parsing logic or the physics notation.

Core nodes represent concepts such as repositories, modules, functions, classes, data models, handlers, services, transformers, UI surfaces, databases, queues and external systems.

Core edges represent relationships such as calls, imports, containment, dependencies, reads/writes/mutations, data usage, serialization, validation, persistence, requests, events, ownership, data/control flow, loading, rendering, invocation, process spawning, connections and routing.

Language-specific details remain in `attributes` unless they are useful across ecosystems.

## Evidence and confidence

Every semantic fact can carry evidence. Evidence kinds include:

- static analysis,
- framework analysis,
- integration resolution,
- runtime traces,
- test observations,
- repository history,
- heuristics,
- AI inference.

Each record identifies the detector, source location when known, detail and confidence. AI-generated assertions must never be indistinguishable from parser-derived facts.

Confidence tiers are `verified`, `supported`, `inferred`, and `unknown`.

## Language adapters

Language adapters own semantics defined by a programming/data language itself.

Current V3 language adapters:

- `PythonAdapter`
- `HTMLAdapter`
- `JavaScriptAdapter`

The Python adapter uses Python's standard-library AST and owns modules, classes, functions, methods, lexical containment, imports, project-local call resolution, inheritance, annotations/decorators and async/await relationships.

It does **not** decide that a class is a Django model or that a function is a FastAPI route.

The HTML adapter owns HTML document/UI structure and deterministic boundary facts such as script sources, event-handler names, forms and HTMX requests.

The initial JavaScript adapter owns JavaScript source-level modules, functions, classes, methods, imports, local calls and selected boundary APIs. It is intentionally dependency-free and can later be replaced/enriched by Tree-sitter or TypeScript compiler APIs without changing the canonical graph contract.

## Framework adapters

Framework semantics belong above language parsing.

Built-in Python framework adapters:

- `DjangoAdapter`
- `FlaskAdapter`
- `FastAPIAdapter`

They reclassify/annotate language nodes only when framework evidence supports the role and emit external contracts such as concrete HTTP/WebSocket routes and rendered templates.

A repository may contain multiple compatible frameworks. Auto mode therefore applies every independently detected framework above the confidence threshold, not just one global framework.

The old framework-aware V2 parser remains only behind the explicit `legacy` compatibility path.

## Repository-level orchestration

`FeynMapEngine` no longer asks "what is the repository's language?" It asks "which registered languages are present?"

```text
repository
    │
    ├── PythonAdapter ── framework enrichment ──┐
    ├── HTMLAdapter ────────────────────────────┤
    ├── JavaScriptAdapter ──────────────────────┤
    └── future language adapters ───────────────┤
                                                ▼
                                      merge_language_graphs
                                                │
                                                ▼
                                     unified repository graph
```

The merger creates a repository root, preserves namespaced node identities/evidence and records language/framework detection metadata.

`language=auto` runs every positively detected language adapter. Explicit comma-separated constraints such as `python,javascript` are also supported.

## Integration contracts

Language/framework adapters describe externally observable boundaries using neutral contracts rather than naming the implementation language on the far side.

For example:

```text
JavaScript
http_client: GET /api/items
```

and independently:

```text
Python/FastAPI
http_server: GET /api/items
```

The integration resolver joins the two facts into a `requests` edge with `integration_resolution` evidence.

This prevents pairwise architecture such as "JavaScript-to-Python resolver", "Swift-to-Rust resolver", etc. The number of protocols stays manageable even as the number of languages grows.

Current contract pairs include HTTP, WebSockets, RPC, queues, subprocess/CLI, FFI/native bridges, IPC, databases, sockets, deep links/app routes and file-mediated flow.

Special resource relationships include template rendering → HTML, HTML script loading → JavaScript, and HTML event handlers → JavaScript functions.

See `docs/MULTILANGUAGE_ORCHESTRATION.md`.

## Whole-app example

```text
Python home()
    │ renders
    ▼
index.html
    │ loads
    ▼
app.js
    │ contains
    ▼
loadItems()
    │ requests GET /api/items
    ▼
Python items()
```

The final graph can answer questions about this entire chain rather than treating each file/language as a separate project.

## Non-web systems

The integration layer is intentionally not browser-centric.

Examples that fit the same model:

```text
Electron JS --ipc_send--> native/main process
JavaScript --process_spawn--> Python CLI
Rust --queue_publish--> Java worker
Swift --ffi_import--> C/C++ export
Python --file_write--> JavaScript reader
Mobile deep_link --routes_to--> native app route
service --socket_client--> daemon socket_server
```

Future Swift/Kotlin/Rust/Java/C++/C#/Go adapters should emit the same boundary vocabulary rather than adding language-pair-specific edge types.

## Ambiguity and unresolved boundaries

A missing integration edge is not proof that no relationship exists.

The resolver connects a boundary only when the contract evidence produces a sufficiently unique target. Dynamic URLs, ambiguous function names, multiple matching services and generated/configured routes stay unresolved.

Resolution is tracked at **individual contract granularity**. If a function exposes five boundaries and one resolves, the other four remain explicitly unresolved.

This is central to anti-hallucination behavior.

## Embedded languages

Embedded language regions are a known hardening area:

- inline `<script>` blocks,
- Vue/Svelte single-file components,
- templated JavaScript/CSS,
- generated code blocks,
- notebook cells.

The intended design is virtual source regions with host/guest provenance. The HTML adapter should not eventually become a JavaScript parser merely because JavaScript can be embedded in HTML.

## Query layer

`FeynMapQuery` is the first stable consumer interface for humans and AI. It supports symbol resolution, dependencies, callers, reverse impact traversal, context bundles and claim validation over the unified graph.

Claim validation is conservative: a missing edge means FeynMap currently has no evidence for the relationship, not that the relationship is impossible.

## Migration layer

`MigrationPlanner` consumes the unified semantic graph; it is not part of parsing.

A complete Rust migration pipeline should eventually be:

```text
unified semantic graph
    ↓
state + mutation + ownership analysis
    ↓
I/O / protocol / async boundary analysis
    ↓
migration units
    ↓
target architecture plan
    ↓
code generation
    ↓
compile/test
    ↓
behavior comparison
    ↓
repair loop
```

Cross-language edges matter here because a migration unit cannot be chosen safely if the planner cannot see its HTTP clients, templates, CLI callers, queue consumers, native bridges or files shared with other components.

## Multi-source truth

Static analysis is necessary but not sufficient for highly dynamic systems. The canonical graph is designed to accept runtime call paths, tests/coverage, database/query traces, message flows, git co-change relationships, compiler/type-checker facts and production telemetry.

These sources enrich rather than overwrite stronger evidence.

## AI integration

After repository orchestration, the next major phase is the persistent AI grounding service/MCP layer.

Planned tools include `get_symbol`, `find_callers`, `find_dependencies`, `trace_path`, `change_impact`, `validate_claim`, `find_entrypoints`, `find_dead_code`, `find_integrations` and `migration_plan`.

Every response should preserve evidence, confidence and unresolved boundaries so an agent can reason about uncertainty.

## Physics notation

The Feynman-inspired model remains a visualization/interpretation layer, not the canonical schema:

```text
Canonical Unified Semantic Graph
        ├── JSON
        ├── grounded query API
        ├── integration topology
        ├── migration engine
        ├── MCP
        └── physics notation / diagrams
```
