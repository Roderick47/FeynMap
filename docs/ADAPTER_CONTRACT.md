# Adapter Contract

## Language adapters

Implement `LanguageAdapter` from `feynmap.adapters.base`.

A language adapter must:

1. detect whether it can analyze a repository,
2. parse without executing untrusted project code whenever possible,
3. emit canonical `SemanticNode` and `SemanticEdge` objects,
4. attach source evidence and confidence,
5. preserve language-specific details in `attributes`,
6. report uncertainty instead of manufacturing relationships.

A language adapter **must not classify framework roles**. Python should emit a class as a Python class, not a Django model; TypeScript should emit a function as a TypeScript function, not an Express route. Framework meaning is a separate enrichment step.

The engine can run multiple language adapters for one repository. Adapters therefore must namespace IDs by language/module/file so their graphs can coexist safely.

Current built-in language adapters are:

- `PythonAdapter` — standard-library AST, framework-neutral Python semantics.
- `HTMLAdapter` — HTML/template documents and UI integration boundaries.
- `JavaScriptAdapter` — initial deterministic JavaScript source analysis and runtime-boundary contracts.

## Framework adapters

Implement `FrameworkAdapter`.

A framework adapter consumes an already-built language graph and enriches it. It may identify routes, models, serializers, dependency injection, ORM behavior, middleware, lifecycle hooks, templates, queues, or other framework-level concepts.

Framework adapters should:

1. declare the language they enrich,
2. detect themselves independently of language detection,
3. preserve existing language facts,
4. reclassify or annotate nodes only when framework evidence supports the role,
5. add evidence with `EvidenceKind.FRAMEWORK`,
6. never become a second parser for language syntax that the language adapter already owns,
7. emit concrete integration contracts when the framework defines an external boundary such as an HTTP route or rendered template.

Built-in Python framework adapters currently include `DjangoAdapter`, `FlaskAdapter`, and `FastAPIAdapter` under `feynmap/adapters/frameworks/`.

## Repository orchestration order

The engine now follows this order:

```text
repository
  ↓
detect all applicable languages
  ↓
run each language adapter independently
  ↓
apply matching framework adapters to each language graph
  ↓
merge language graphs under one repository root
  ↓
resolve cross-language / cross-runtime integration contracts
  ↓
unified semantic graph
```

`--framework none` skips framework enrichment. `--language python,javascript` can constrain a scan; `--language auto` runs every positively detected built-in adapter.

## Integration contracts

Language/framework adapters should emit language-neutral integration contracts for externally observable boundaries rather than hard-coding another language on the far side.

For example, a JavaScript adapter should emit:

```text
http_client: GET /api/items
```

not:

```text
calls_python_function: items
```

The Python/Java/Rust/etc. server adapter independently emits `http_server`, and the integration resolver joins the compatible evidence.

Current contract vocabulary includes:

- `http_client` / `http_server`
- `websocket_client` / `websocket_server`
- `rpc_client` / `rpc_server`
- `queue_publish` / `queue_subscribe`
- `process_spawn` / `cli_entrypoint`
- `ffi_import` / `ffi_export`
- `ipc_send` / `ipc_receive`
- `database_client` / `database_server`
- `socket_client` / `socket_server`
- `deep_link` / `app_route`
- `file_write` / `file_read`
- `template_render`
- `script_load`
- `event_handler`
- `config_read`

See `docs/MULTILANGUAGE_ORCHESTRATION.md` for the resolution model and examples.

## Evidence rule

Adapters should prefer this hierarchy:

1. compiler/parser/type-checker fact,
2. framework configuration fact,
3. integration resolution from two independently evidenced contracts,
4. test/runtime observation,
5. repository-history evidence,
6. deterministic heuristic,
7. AI inference.

AI inference must always be labeled `ai_inference` and must not silently replace stronger evidence. Cross-boundary resolver edges use `integration_resolution` evidence.

## IDs

Node IDs must be stable within a repository and, where possible, include language + module/file scope to avoid collisions. Edge IDs must be deterministic for the same observed relationship.

## No execution by default

Static adapters should not import or execute analyzed application code by default. Runtime evidence must be opt-in and clearly identified.

## Ambiguity

An adapter may emit a contract even when the far side is not yet known. The resolver should connect it only when the target is unique enough to justify the edge. Ambiguous matches remain unresolved and are reported in graph metadata rather than guessed.
