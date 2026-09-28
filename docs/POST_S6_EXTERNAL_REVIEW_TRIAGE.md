# Post-S6 external-review triage and revised development pathway

Review input: exploratory Claude review across MDN Django tutorial, Miguel Grinberg Flask microblog and Django REST Framework. These are **provisional observations**, not accepted accuracy benchmarks. Record repository revisions, task prompts, and independent gold labels before claiming percentages.

## Policy

Pause additional Rust and substrate optimization. The S6.9 Rust accelerator remains optional, with Python as the default. Prioritize whether the knowledge graph is true, whether delivered context contains implementation instead of distractors, and whether coding agents complete tasks with fewer tokens/cost. Do not make a 22x isolated route result into a full-application claim.

## Immediate P0 cleanup (implemented on this review branch)

- The JavaScript adapter now skips `*.min.js` by default, retaining an explicit diagnostic; first-party JS in the same repository remains analyzed.
- If separate definitions collide under the historical `path|name|line` identity, disambiguate later definitions with their start offsets and a diagnostic. Existing unambiguous IDs stay unchanged. Preserve strict graph duplicate detection rather than silently suppressing nodes.
- New regression fixtures cover same-name declarations on one line and minified vendor files.
- Fix malformed literal `\n` characters in the Rust build `.gitignore` entries.
- Remove obsolete root `__init__.py` (the installable package is `feynmap/`) and `main_broken.py` from the active checkout; their original commits remain in Git history.
- Remove five tracked `__pycache__/*.pyc` files. Ignore rules alone cannot untrack already committed files.
- Use `ast.Constant.value` in the two legacy string-literal helpers instead of deprecated `ast.Str/.s` aliases. This change is not a blanket claim of Python 3.14 support.
- Add source-tree hygiene regressions and run regular Python 3.8/3.12 plus recursive self-check CI.

## P0 follow-up: reproduce the external defects on pinned repositories

Create external regression manifests for the MDN Django tutorial, Miguel Grinberg's Flask microblog and Django REST Framework. Record immutable repository commit, runtime, framework version, exact query/task, expected grounded nodes/edges, unresolved diagnostics, expected nonmatches, raw outputs and analysis time/memory.

The claimed MDN counts (e.g., 2/32 template connections) and DRF test-context shares (35%, 66%) are exploration notes until replayed against pinned checkouts. Compare baseline and fixes without using these same examples as the final held-out R1 repair corpus.

## P1: framework semantics must precede higher-level ranker changes

1. Django CBV attributes: resolve `model = Book`, `queryset = Book.objects...`, explicit `template_name`, and known default class-based-view template conventions with correct evidence tiers. Where multiple symbols could match, preserve unresolved ambiguity rather than guess.
2. AppConfig: distinguish framework membership/lifecycle from a task-relevant dependency. Prevent ubiquitous AppConfig hub edges from crowding impact and sparse-route results; preserve framework membership as evidence/metadata or separately typed structural relationship under contract-version safeguards.
3. URL reversing: resolve static Django `reverse`, `reverse_lazy`, `{% url 'name' %}` and namespace mappings against registered named routes. Unknown/dynamic template tags should be labeled unresolved, not emitted as literal HTTP client destinations.
4. Flask: compose Blueprint `url_prefix` values with registered blueprint route decorators using import/registration evidence. Keep dynamic registration unresolved.
5. DRF: extract grounded `permission_classes`, serializer/model bindings, and route coverage. Explicitly distinguish routed vs unrouted handlers; a server endpoint lacking an in-repository client is NOT by itself a failed integration.
6. Split diagnostics into unresolved dynamic call, missing target, legitimate external endpoint, and unreferenced server route. Exclude well-known built-in operations from actionable unresolved-call counts without concealing genuinely unresolved calls.

Each semantic change requires a small source-authored fixture, an independent expected graph and a before/after activation/impact benchmark. Record any compatibility effects on frozen graph and analysis contracts.

## P2: context-selection quality

- Introduce typed context channels/budgets: implementation, tests, migrations, vendored/generated assets, documentation and unresolved evidence. Tests remain available but cannot win the entire core-implementation budget by repeating the task vocabulary.
- Compare DRF throttling/serializer cases and Django migrations against explicit independent essential-implementation labels, plus a countercase where tests are genuinely essential.
- Measure essential symbol/file recall, irrelevant-context ratio, selected test-token share, total delivered tokens, downstream repair success and unnecessary extra searches. Do not optimize only for fewer tokens.

## P3: usable local surface

- Add `feynmap context '<task>' --path . --max-tokens ... --format json` using the existing `SparseContextPipeline` instead of inventing a second retrieval engine. Support an existing immutable snapshot and explicit analysis/rebuild behavior.
- Include evidence provenance, omissions, unresolved facts, token counts and version/snapshot identity in output.
- Keep `feynmap claim`/`validate_claim` visible as a separate differentiator: source-backed verification of statements an AI agent makes about code relationships.
- Then revive the parked PR #22 as an **implementation reference only**, rebuilding local stdio MCP from current `main` and the current frozen grounding catalog. Core remains Python 3.8+, MCP can be optional on Python 3.10+.

## S7 revised: external task-level evaluation

- S7.1: first freeze an 8-task SWE-bench Verified pilot via existing R1 tooling (not five repeatedly tuned Wikonomi cases). Independently label entry files/symbols and acceptance tests.
- S7.2: run all current four sealed experimental arms with one pinned provider/model/prompt/tool set, randomized/rotated arm order, fresh disposable workspaces and total input/output token accounting.
- S7.3: after checking pilot harness integrity, pre-register a **new** 15–20 task held-out corpus across larger, previously untuned repositories. Include a fair repo-map comparator (e.g., Aider-style) and a no-context baseline with comparable budgets; version the four-arm benchmark schema if the comparator becomes an additional arm. Never change an already locked corpus/arms to fit a preferred result.
- S7.4: measure official task resolved rate, patch correctness, unnecessary files changed, unsupported code-path claims, first-edit localization, additional searches, time, tokens and total model/tool cost. Report confidence intervals/paired task-level deltas where feasible. Freeze policy before the held-out results.

## P4: packaging and experiment lineage

- Current `pyproject.toml` explicitly installs generic top-level modules including `main`, `config` and `pipeline`; this is **confirmed but not changed in this safety patch**. Design a separate compatibility-tested migration to package-qualified `feynmap.legacy` modules, retain an explicit V2 CLI shim and test an installed wheel from a clean unrelated working directory.
- Only after the package migration, move versioned ranker/repair-role experiments out of the active runtime where safe. Preserve their manifests, result history and reproducibility; no blind deletion.
- License: retain the owner's current proprietary/all-rights-reserved position. Before outside beta access, write explicit evaluator/developer access terms and distribution obligations; do not silently switch to an open-source license.

## Acceptance priority

Crash-free analysis and ordinary installation > independently correct graph facts > grounded essential implementation retrieval > usable local CLI/MCP > held-out agent task quality and total cost. New Rust optimizations require a fresh whole-workflow bottleneck, not the old isolated route benchmark.
