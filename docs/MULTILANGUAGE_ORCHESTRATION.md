# Multi-Language Repository Orchestration

FeynMap models a repository as one software system, not as one programming language.

A modern application can cross language and runtime boundaries many times during a single user action. A browser click may pass through HTML, JavaScript, HTTP, Python and SQL. A desktop app may cross JavaScript/Electron IPC into native code. A mobile app may cross Swift/Kotlin, WebView JavaScript, deep links, HTTP services and native FFI. A data pipeline may connect Python, shell scripts, a compiled binary, files and a message queue.

The semantic graph must be able to represent all of those as one evidence-backed topology.

## Repository pipeline

```text
repository
    |
    +--> PythonAdapter ---------+
    +--> HTMLAdapter -----------+
    +--> JavaScriptAdapter -----+----> merged repository graph
    +--> future Rust/Java/... --+                |
                                                 v
                                      framework enrichment
                                                 |
                                                 v
                                      integration resolver
                                                 |
                                                 v
                                      unified semantic graph
```

`FeynMapEngine` runs every registered language adapter that positively recognizes the repository when `language=auto`. A user can also constrain analysis with a comma-separated selection such as `python,javascript`.

Language graphs keep language-specific node IDs and evidence. They are merged beneath a repository node rather than flattened into anonymous files.

## Integration contracts

Adapters describe externally observable boundaries with language-neutral contracts stored on semantic nodes. The resolver joins compatible contracts only when the evidence is sufficiently specific.

Examples:

| Producer/client contract | Consumer/server contract | Semantic edge |
| --- | --- | --- |
| `http_client` | `http_server` | `requests` |
| `websocket_client` | `websocket_server` | `connects_to` |
| `rpc_client` | `rpc_server` | `requests` |
| `queue_publish` | `queue_subscribe` | `emits` |
| `process_spawn` | `cli_entrypoint` | `spawns` |
| `ffi_import` | `ffi_export` | `invokes` |
| `deep_link` | `app_route` | `routes_to` |
| `ipc_send` | `ipc_receive` | `flows_to` |
| `database_client` | `database_server` | `connects_to` |
| `socket_client` | `socket_server` | `connects_to` |
| `file_write` | `file_read` | `flows_to` |

Special resource relationships are also resolved:

- `template_render` → HTML document (`renders`)
- HTML `script_load` → JavaScript module (`loads`)
- HTML `event_handler` → JavaScript function (`invokes`)

Contracts carry target/channel information, confidence and adapter-specific metadata. The resulting edge carries `integration_resolution` evidence and records whether the edge crossed a language boundary.

## Web example

```text
Python home()
    |
    | renders
    v
index.html
    |
    | loads
    v
app.js
    |
    | contains
    v
loadItems()
    |
    | GET /api/items
    v
Python items()
```

The HTML adapter discovers the script source and event handler. The JavaScript adapter discovers the function and `fetch()` request. Flask/FastAPI/Django enrichment exposes backend route contracts. The integration resolver joins the compatible facts.

## Non-web and app examples

The same resolver is intentionally protocol-oriented instead of web-oriented.

### Process orchestration

```text
JavaScript launcher()
    |
    | process_spawn: worker.py
    v
Python worker.py CLI entrypoint
```

### Queue-based services

```text
Rust service
    |
    | queue_publish: orders.created
    v
Java worker
    queue_subscribe: orders.created
```

### Native/mobile bridge

```text
React Native JavaScript
    |
    | ffi_import: CameraModule
    v
future Kotlin/Swift native export
```

JavaScript currently recognizes common Electron IPC, React Native `NativeModules`, React Native WebView messaging, WKWebView messaging and deep-link calls. Future Swift/Kotlin adapters should emit the matching `ipc_receive`, `ffi_export`, `app_route`, HTTP and database contracts rather than introducing mobile-only graph concepts.

### File-mediated flow

```text
Python exporter
    |
    | file_write: shared/data.json
    v
JavaScript importer
    file_read: shared/data.json
```

This is useful for ETL, build systems, scientific pipelines, desktop tools and legacy integrations where no direct call exists.

## Current language depth

### Python

The Python adapter remains framework-neutral and maps modules, classes, functions, methods, imports, local calls, inheritance and async relationships. A separate framework-neutral boundary pass detects selected HTTP clients, subprocesses, file I/O, environment reads, database connection calls and native-library loading.

Django, Flask and FastAPI then add framework semantics and concrete backend route/template contracts.

### HTML

The HTML adapter maps each HTML/template document as a UI surface and records static script loads, DOM event-handler names, forms, HTMX requests and internal navigation targets.

### JavaScript

The first JavaScript adapter is deliberately dependency-free and source-based. It maps modules, functions, arrow functions, classes, methods, imports, local calls and inheritance where deterministically visible. It also emits integration contracts for HTTP, WebSockets, subprocesses, files, Electron IPC, deep links, environment reads and selected native/mobile bridges.

This JavaScript implementation is a foundation, not the final parser. A parser-backed Tree-sitter or TypeScript-compiler implementation can later replace/enrich it without changing the semantic graph or resolver.

## Ambiguity rule

FeynMap does not invent an integration edge just because two things look related.

If one client contract matches multiple possible servers, if a route is constructed dynamically, or if a target name cannot be resolved uniquely, the contract remains unresolved. `graph.metadata.integration` records resolved counts and unresolved contract samples.

This is important for AI grounding: "unresolved" means FeynMap needs more evidence, not that the relationship is impossible.

## Embedded languages

Inline JavaScript inside HTML, Vue/Svelte single-file components, templated JavaScript/CSS and similar embedded-language regions are a known hardening item. The long-term design should treat embedded code as virtual source regions with host/guest provenance rather than forcing the host adapter to pretend it understands the guest language.

## Adapter guidance for future languages

New adapters should map native language semantics first, then emit integration contracts for observable boundaries.

Examples:

- **Rust:** Axum/Actix HTTP servers, reqwest clients, Tokio processes, files, sockets, channels, `extern` FFI.
- **Java:** Spring endpoints, HTTP clients, Kafka/JMS, JDBC, process execution, JNI, files.
- **C/C++:** exported/imported symbols, sockets, files, subprocesses, shared libraries, IPC.
- **C#:** ASP.NET endpoints, HttpClient, process execution, P/Invoke, queues, files.
- **Go:** `net/http`, gRPC, processes, files, sockets, cgo.
- **Swift:** URLSession, registered URL schemes/app routes, WKScriptMessageHandler, native exports, files/databases.
- **Kotlin:** Retrofit/OkHttp, Android intents/deep links, JavascriptInterface/WebView bridges, JNI, files/databases.
- **Shell/build languages:** CLI entrypoints, spawned commands, files, pipes and build artifact flow.

The resolver should grow by protocol/interaction type, not by hard-coded language pairs. That keeps the number of relationships manageable as FeynMap adds languages.
