# Phase 1: Framework-neutral Python

Phase 1 establishes a strict boundary between Python semantics and framework semantics.

## Completed

- `PythonAdapter` now uses Python's standard-library AST directly.
- It emits framework-neutral modules, classes, functions, methods, imports, calls, inheritance, annotations, and await relationships.
- `DjangoAdapter`, `FlaskAdapter`, and `FastAPIAdapter` enrich the generic graph only after Python analysis.
- Framework detection is independent from language detection.
- `--framework none` exposes the raw Python graph.
- The V2 framework-aware extractor remains available only through `feynmap legacy` and lazy compatibility exports.
- Regression tests prove that Django-looking source is initially represented as ordinary Python before framework enrichment.

## Boundary rule

New framework behavior must not be added to `feynmap/adapters/python.py`.

If a behavior is defined by Python itself, it belongs in the Python adapter. If it is defined by Django, Flask, FastAPI, or another library/framework convention, it belongs in a framework adapter.

This boundary is what makes future combinations possible without duplicating parsers:

```text
Python      + Django / Flask / FastAPI
TypeScript  + Express / NestJS / Next.js
Java        + Spring
C#          + ASP.NET
Rust        + Axum / Actix
```

## Next

Phase 2 turns the semantic graph into a durable AI grounding service: persistent snapshots, incremental updates, MCP tools, and context retrieval designed for coding agents.
