# LLM grounding review — 10 September 2026

Reviewed main at `6a236608d819532274c91574b0508e872a848b11`, with emphasis on Python resolution, stored context, query dispatch, and repository orientation. This is a targeted review, not proof of correctness of every adapter.

## Findings addressed

1. **Package re-exports resolved to placeholders.** `python_reexports.py` included external-system placeholders in the definition index. Those placeholders could terminate alias resolution before reaching the actual local class. Excluding them restores transitive package calls and the type aliases used by instance dispatch. The existing three re-export tests reproduced this failure.
2. **Ambiguous names silently selected a symbol.** `FeynMapQuery.resolve` accepted the first exact short-name match even when several definitions shared that name. Stable IDs now win; exact names outrank partial matches; multiple matches require disambiguation.
3. **Tool limits were descriptive only.** `GroundingService.call` did not enforce the published input schema. It now checks required and unknown fields, string/integer types, integer bounds, and enum values before dispatch. Numeric strings and booleans are intentionally rejected for integer arguments.
4. **Budget accounting omitted its own estimate.** Stored context now measures the complete response, including the estimate field. A root that cannot fit produces an explicit error rather than an oversized success response. The four-character estimate is a heuristic, not a vendor-token guarantee.
5. **Repository summaries lacked navigation.** Summary responses now include bounded module/file and handler lists plus symbols ranked by distinct evidenced callers. Each carries an ID and available source/evidence metadata for follow-up queries. Ranking does not establish business importance.

## Remaining weaknesses and implementation order

### 1. Make context selection preserve useful relationships

`StoredSnapshotContext.context_bundle` fills the node budget before adding edges, and removes relationships first when trimming. Large neighborhoods can therefore become disconnected symbol lists. Select a root-adjacent edge and its missing endpoints atomically, reserve metadata space first, then expand connected paths by distance and relevance. Test a large fan-out under small budgets, evidence-heavy nodes, Unicode, and deterministic output. Add an optional real tokenizer while retaining an explicitly approximate portable mode.

The new orientation lists have count limits, but the whole summary is not token-budgeted: diagnostics, integration samples, names and evidence can still be large. Add a repository-wide budget and omission counts before exposing it as a universally small snapshot.

### 2. Separate relationship semantics

`query.callers` currently traverses every incoming relationship, including containment and imports. `impact` aliases that traversal. Introduce explicit edge filters: callers should follow call/invocation edges; dependency and impact queries need separately documented relation sets. Preserve compatibility through a versioned query contract. Test that a containing module is not reported as a function caller.

### 3. Measure uncertainty and analysis coverage separately

`core/ontology.py` derives “verified” from numeric confidence and evidence count; evidence existence alone does not prove semantic accuracy. JavaScript scanning emits static evidence with detector-assigned confidence. Distinguish syntactic observation, resolved binding, heuristic match, and runtime observation. Report analyzed, skipped, unsupported, and failed files by language, plus unresolved relationships. Never describe evidence coverage as analysis recall.

### 4. Strengthen parsers and binding semantics

`adapters/javascript.py` uses regular expressions and supports `.js`, `.mjs`, `.cjs`, and `.jsx`, not TypeScript. A parser-backed JS/TS adapter should handle lexical scopes, imports, nested syntax, and syntax errors with explicit provenance. Python re-export enrichment still needs adversarial fixtures for parameter/local shadowing, reassigned imports, conditional exports, and dynamic `__all__`; these are not solved by the placeholder fix.

### 5. Test protocol matching against false positives

The integration resolver is broad, but matching a path or boundary signature is not sufficient evidence of deployment connectivity. Add negative fixtures for identical routes on different services, HTTP methods, host/port differences, composed route prefixes and dynamic URLs before increasing coverage. Keep ambiguous matches unresolved.

### 6. Finish the LLM delivery surface and evaluation

Main contains a transport-neutral `GroundingService`, not a complete MCP server. Review the outstanding transport work separately before integrating it. Expose summary → symbol discovery → focused context → evidence/unknowns as the primary workflow, using immutable snapshot IDs throughout. Add pagination or output bounds to currently unbounded symbol/caller/dependency responses.

Use benchmark repositories with annotated expected and forbidden edges. Track precision, recall on those fixtures, unsupported coverage, snapshot latency, response size, and whether an LLM can answer architecture/change questions with source citations. Keep self-analysis as one benchmark, not the only one.

## Product direction

Prioritize reliable, compact codebase understanding before language conversion or arbitrary non-code structures. The language-neutral graph is useful infrastructure; the immediate product value comes from identifying the right symbols, showing their evidenced relationships, and making missing coverage visible without flooding the LLM's context.
