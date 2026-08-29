# AI Grounding

FeynMap is intended to give coding agents a repository model they can query instead of repeatedly reconstructing architecture from partial file context.

## Grounding layers

The semantic graph is built in layers:

1. a language adapter extracts syntax and language semantics,
2. an optional framework adapter enriches those facts,
3. evidence and confidence remain attached to every resulting fact,
4. query/MCP consumers retrieve only the grounded context they need.

The Python implementation now follows this boundary directly: `PythonAdapter` is framework-neutral, while Django, Flask, and FastAPI are separate enrichment adapters.

## Conservative answers

A missing relationship means **no current evidence**, not impossibility. AI-facing tools should preserve that distinction.

For example, if an agent claims `PaymentView -> FraudDetector`, `validate_claim` should return the matching evidence when it exists. If no edge exists, it should report the claim as unsupported and surface nearby known relationships rather than inventing certainty.

## Target MCP surface

Phase 2 should expose small, evidence-preserving tools such as:

- `get_symbol`
- `find_callers`
- `find_dependencies`
- `trace_path`
- `change_impact`
- `validate_claim`
- `find_entrypoints`
- `context_bundle`

These tools should query a persistent repository snapshot instead of re-parsing the entire repository for every request.

## Evidence preservation

Every AI-facing response should retain source location, detector, evidence kind, and confidence wherever available. AI inference may enrich the graph, but it must remain visibly distinct from parser, framework, runtime, test, history, and compiler evidence.
