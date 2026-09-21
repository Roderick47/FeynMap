# Real-world AI validation plan

This plan defines when FeynMap is ready to move from offline judgment
experiments into real coding-agent use. Progress is milestone-based rather than
date-based: each checkpoint has an observable entry gate, a bounded kind of
testing, and evidence required before widening usage.

FeynMap remains the read-only grounding layer throughout these checkpoints.
An AI coding agent may edit a disposable worktree or feature branch using its
own tools, but FeynMap does not gain repository mutation or command-execution
authority as part of this plan.

## Testing checkpoints

| Checkpoint | Entry gate | What the project owner can test | Scope |
| --- | --- | --- | --- |
| R0: manual grounding trial | Available now | Run snapshot/query/context and v1R output, then provide the results manually to an AI | Read-only, observational, no direct agent integration |
| R1: controlled repair trial | Held-out repair benchmark harness and run manifests are complete | Ask an AI to repair deliberately selected tasks with and without FeynMap context | Disposable worktrees, human-triggered, tests required |
| R2: local MCP alpha | Read-only stdio MCP transport and protocol tests pass | Connect a local AI coding agent directly to stored FeynMap snapshots for real repository tasks | Personal/local repositories, feature branches, human review |
| R3: mixed-language alpha | Tree-sitter JavaScript/TypeScript conformance gates pass | Use the local AI integration on representative Python + JavaScript/TypeScript systems | Mixed-language repositories, parser provenance visible |
| R4: team beta | Multi-source evidence and repeatable outcome telemetry are available | Use FeynMap-assisted agents in normal review/maintenance workflows | Selected team repositories with CI and review gates |
| R5: remote pilot | Authentication, tenant isolation, privacy policy, and shared storage are verified | Test a remotely hosted grounding service | Explicitly authorized repositories and users only |

The first meaningful **real-world integrated AI usage** begins at R2. R0 can be
used now for manual learning, and R1 is the first scientifically controlled AI
repair test, but neither yet represents normal day-to-day agent use.

## R0: manual grounding trial — available now

Use FeynMap's current CLI and stored snapshots on a non-critical repository.
Give an AI the resulting context bundle or dual-channel report manually and
observe whether it identifies the correct symbols and files.

Record:

- task description;
- snapshot ID and Git revision;
- FeynMap command and output schema;
- files and symbols proposed by the AI;
- files actually changed;
- tests executed and results;
- obvious unsupported claims; and
- approximate AI input/output cost.

R0 is useful for discovering workflow problems, but its results are not a
benchmark because prompts and operator behavior are not controlled.

## R1: controlled repair trial

Build a provider-neutral benchmark runner over new held-out tasks. It must not
reuse the five frozen Wikonomi changes to tune retrieval or judgment policy.

Each task should run at least these arms:

1. AI with ordinary repository access and no FeynMap context;
2. AI with deterministic FeynMap context;
3. AI with relevance-ranked FeynMap context; and
4. AI with relevance context plus non-destructive repair-role guidance.

Required measurements:

- task tests passed;
- patch accepted by an explicit task oracle;
- correct and unnecessary files changed;
- first proposed edit file/region;
- unsupported symbol, relationship, or path claims;
- repository searches and extra context requests;
- elapsed time and model/provider tokens; and
- snapshot, graph, prompt, model, and tool-contract versions.

The benchmark runner should save immutable run manifests so failures can be
replayed and model or graph changes can be compared rather than remembered
anecdotally.

R1 exits only after the harness can reproduce baseline and FeynMap-assisted
runs without leaking gold labels into model state.

## R2: local MCP alpha — first normal real-world use

Expose the existing `GroundingService` through a local read-only stdio MCP
adapter. The expected packaging is an optional Python 3.10+ MCP component while
the dependency-free core retains its existing Python compatibility, unless a
separate packaging decision supersedes it.

Entry gates:

- official MCP SDK registration for the versioned grounding catalog;
- schema validation and protocol conformance tests;
- queries operate on immutable stored snapshots without hidden reparsing;
- evidence, confidence, omissions, and unresolved facts survive transport;
- no repository-edit or arbitrary-command tool is exposed;
- repository/snapshot selection is explicit; and
- controlled R1 results provide a baseline for judging actual usage.

At R2 the project owner can connect an AI coding agent to FeynMap and use it on
real tasks in a feature branch. Every patch still requires ordinary code review
and project tests. Initial use should favor codebases already covered well by
the Python, HTML, and current JavaScript adapters.

The alpha should capture a local, privacy-preserving feedback record: tools
called, snapshot IDs, result sizes, omissions, unresolved facts, whether the
answer helped, and final test outcome. Source excerpts and prompts should not be
uploaded automatically.

## R3: Tree-sitter mixed-language alpha

Tree-sitter is a planned graph-quality foundation, not merely a parser swap.
The implementation sequence is:

1. shared parser lifecycle, byte/line source regions, error recovery, parser
   provenance, and deterministic identity rules;
2. parser-backed JavaScript with side-by-side conformance against the current
   dependency-free adapter;
3. first-class TypeScript syntax and module relationships; and
4. optional TypeScript compiler enrichment for resolved type/module facts that
   syntax alone cannot prove.

Promotion gates:

- stable identities across clones and repeated runs;
- no loss of currently supported JavaScript symbols, calls, and integration
  contracts without an explicit compatibility decision;
- fixtures for modern syntax, JSX/TSX, parse errors, and embedded regions;
- adapter evidence identifies Tree-sitter grammar/version and source span;
- snapshot and semantic-diff compatibility tests pass; and
- mixed-language repair tasks are added to the held-out R1 corpus.

After these gates pass, real-world AI testing can expand to JavaScript- and
TypeScript-heavy repositories with substantially stronger source grounding.

## R4: team beta

Before wider routine use, add evidence beyond static analysis:

- test and coverage relationships;
- compiler/type-checker diagnostics;
- Git co-change evidence;
- selected runtime traces; and
- explicit conflict handling between evidence sources.

The team beta requires repeatable task-success telemetry, clear fallback when
FeynMap is uncertain, CI integration, and documented snapshot retention and
privacy behavior.

## R5: remote pilot

Remote MCP comes after local value is demonstrated. It requires authentication,
authorization by repository, tenant isolation, encrypted transport, audit
logging, data-retention rules, deletion behavior, and a deliberate repository
ingestion model. A snapshot identifier alone must never grant access.

## Stop and rollback conditions

Pause expansion to the next checkpoint if any of these occur:

- FeynMap-assisted agents pass fewer held-out tasks than the relevant baseline;
- context or role policy hides candidates that deterministic retrieval found;
- unsupported graph claims are presented as verified facts;
- snapshot identity or result ordering becomes nondeterministic;
- token or latency cost grows without a measured task-success benefit;
- Tree-sitter migration silently loses established graph facts; or
- local/remote integration exposes source outside its authorized boundary.

Experimental improvements remain shadow outputs until their relevant gate
passes. A successful fixture result alone is not sufficient for promotion.
