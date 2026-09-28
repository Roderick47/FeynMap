# Adversarial resolution hardening

This phase expands the language-neutral evaluator introduced in PR #25 with
source-authored scope and HTTP fixtures. It fixes the failures they exposed.

## Changes

- Python re-export enrichment consults the standard-library compiler symbol table
  before restoring an imported call edge. Local, parameter, free, and nonlocal
  bindings cannot silently become module-import targets. Assigned module names
  are excluded from the static import index. Comprehensions are conservatively
  skipped in this enrichment pass because they introduce separate scopes.
- The JavaScript fallback scanner masks comments and strings while preserving
  offsets and line breaks for definition and local-call analysis. Nested
  declaration bodies are excluded from enclosing functions' calls. Member calls
  are not resolved as bare same-named functions. Candidate function targets are
  restricted to visible enclosing scopes and ambiguity is left unresolved.
- Fetch method scanning stops at that call's balanced closing parenthesis rather
  than reading an arbitrary 220 characters into subsequent statements. Fetch
  matches inside masked strings/comments are ignored.
- Analysis contract **1.2.0** forces the existing conservative incremental planner
  to refresh older analysis rather than reuse graphs produced by the old rules.

The shared graph, annotation format and evaluator remain language-neutral. The
language-specific rules live in adapters, where syntax and binding rules belong.

## Evidence and review status

See [fixture review record](../tests/fixtures/adversarial/REVIEW.md) for all 13
source rationales, before/after measurements, and runtime witness details. The
baseline produced seven false bindings and missed one expected relationship.
The corrected implementation passes every label.

The execution witnesses use Python and Node independently of the analyzer, but
that is **not independent human review**. External review of the annotation
package remains pending. No external reviewer was contacted.

## Remaining limitations

This is targeted hardening, not a full JavaScript parser or complete binding
analysis. The lexical helper masks entire template literals, including embedded
expressions. Regex literals, complex arrow bodies, JavaScript parameter/local
shadowing, dynamic object members, and imported aliases need additional fixtures
and parser-backed handling. Most other boundary detectors still scan raw source.
Fetch options with nested/computed/spread properties or dynamic methods are not
fully resolved by the literal method matcher.

Python global mutation, dynamic exports, execution order and interprocedural
callback targets also require more work. Skipping unresolved cases can reduce
recall; it should not be mistaken for proof that no relationship exists. Runtime
witnesses corroborate only their particular inputs, not every possible execution.

## Validation

Run `python -m pytest` for the full suite and
`python -m pytest tests/test_adversarial_fixtures.py` for the six new tests. The
latter include the three annotated benchmarks, Python/Node execution witnesses,
and a mask/parenthesis boundary regression check. Existing mixed-language and
self-hosting gates remain in place.
