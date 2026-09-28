# Branch cleanup audit — pre-Rust checkpoint

This audit records the branch state after the S0-S6 substrate line was
consolidated into `main` through PR #34.

The goal is to prevent historical branches from being mistaken for active,
parallel implementations.

## Authoritative development line

```text
main
```

Current main includes the sparse substrate through S6.3, recovered adversarial
resolution fixes, frozen cross-runtime contracts, and the recursive self-check
CI gate.

`feature/tool-space-routing` has been fast-forwarded to the same commit as
`main`. It is no longer a separate code state and is safe to delete as a
branch name when convenient.

## Audit result

At the time of this audit there are 38 non-main branch names.

- 32 contain **zero unique commits** relative to current `main`.
- 6 branch names diverge from `main`.
- 3 of those 6 are historical merge-commit artifacts with **zero file
  differences** relative to content already reachable from `main`.
- 1 contains an adversarial-resolution commit whose useful behavior and
  fixtures were explicitly recovered into modern `main`.
- 1 contains old V2-only work intentionally retained as an archival reference
  until its remaining useful concepts are either reimplemented in V3 or
  explicitly retired.
- 1 separate transport branch contains 9 unique MCP commits and remains a
  deliberate parked experiment.

The branch-by-branch classification below is authoritative.

## Preserve as historical baselines

These are intentional before/after reference points and should not be treated as
feature branches:

- `baseline/v3.0.0-alpha.1`
- `baseline/self-hosting-pre-type-resolution`
- `baseline/self-hosting-pre-reexport-type-sharing`

They contain no work missing from `main`, but retain benchmark/history value.

## Fully contained historical branches

The following contain no unique commits relative to `main`. They are
historical-only and safe to delete as branch names after any desired external
archival:

- `chore/remove-rails-support`
- `codex/add-semantic-similarity-clustering-feature`
- `codex/fix-issues-in-main_broken.py`
- `codex/implement-change-impact-predictor-feature`
- `feat-stable-graph-schema`
- `feature/active-state`
- `feature/adaptive-sufficiency`
- `feature/jev-guided-search`
- `feature/jev-judgment-layer`
- `feature/language-neutral-evaluation`
- `feature/minimal-sufficient-context`
- `feature/region-first-activation`
- `feature/sparse-knowledge-substrate`
- `feature/tool-space-routing`
- `fix/evidence-based-reachability`
- `fix/llm-grounding-correctness`
- `fix-branch-preserving-traces`
- `fix-component-metrics`
- `fix-evidence-backed-impact`
- `improve/connected-context-confidence`
- `master`
- `merge/phase-1.6-self-hosting`
- `phase-1.6-reexport-resolution`
- `phase-1.6-self-hosting`
- `phase-2a-clone-independent-identity`
- `phase-2a-incremental-context`
- `phase-2a-snapshots-persistence`
- `phase-2b-mcp-groundwork`
- `refactor/semantic-foundation-v3`

## Diverged merge-artifact branches with no unique file content

These show one unique merge commit in ancestry comparison, but comparing their
tips against current `main` yields zero changed files. They contain no unique
implementation to recover and are safe to delete as branch names:

- `fix/framework-auto-detection`
- `fix/globally-unique-node-identities`
- `fix/scope-aware-call-resolution`

Their substantive changes are already present in `main`.

## Recovered adversarial branch

`fix/adversarial-resolution-fixtures` contains one unique historical commit,
but its useful content was explicitly audited during consolidation.

Recovered into modern `main`:

- Python scope-safe re-export/imported-call resolution;
- JavaScript comment/string masking and nested-scope call handling;
- bounded `fetch(...)` method parsing;
- source-authored adversarial fixtures and runtime witnesses;
- the analysis-policy bump to `1.2.0`.

The recovered tests pass on Python 3.8/3.12 and under recursive self-analysis.
This branch is therefore historical-only and safe to delete as a branch name.

## Legacy V2 archive requiring deliberate disposition

`fix/bug-fixes-and-architectural-improvements` has two unique commits from
the pre-V3/V2 implementation. Do **not** treat it as an active development line,
but do not erase it until the remaining useful concepts are deliberately
resolved.

Its work falls into three groups.

### Superseded by stronger V3 mechanisms

- cross-file/import-aware Python call resolution is superseded by the V3 Python
  AST, import and package re-export resolution pipeline;
- static Django URL registration is represented in V3 as grounded
  `http_server` integration contracts;
- evidence-weighted semantic-cluster confidence already exists in the retained
  legacy clustering path;
- canonical V3 nodes carry explicit source locations.

### Legacy-only behavior, not substrate-critical

These affect the old `feynmap legacy` pipeline rather than the frozen sparse
substrate:

- ORM/stdlib mediator suppression in the old V2 extractor;
- semantic ghost/dead-code heuristics;
- separate node-vs-chain complexity reporting;
- duplicate legacy semantic-cluster suppression.

They should only be ported if continued fidelity of the V2 compatibility
command justifies the maintenance cost.

### Useful concepts not yet represented in V3

Two ideas should survive as explicit modern backlog items instead of living
only on this old branch:

1. Django/DRF permission-policy extraction (for example
   `permission_classes`, authentication/admin semantics) as grounded framework
   attributes/evidence.
2. Explicit routed-versus-unrouted Django handler coverage, derived from
   resolved URL contracts without treating absence as impossibility.

Until those backlog items are resolved, retain this branch only as an archival
reference. New implementation must occur from current `main`, not by reviving
the old V2 branch.

## Parked independent experiment

`phase-2b-stdio-mcp` contains 9 unique commits and remains intentionally
separate.

PR #22 is marked draft/parked. It predates the current frozen contract set and
must not be merged as-is. If revived, the stdio transport should be
reimplemented/rebased from current `main` and validated against:

- frozen S6 contract conformance;
- recursive self-check;
- current grounding-tool catalog;
- Python runtime/packaging policy;
- the current MCP SDK.

This is the only intentionally retained non-baseline branch with independent
feature implementation.

## Open pull requests after cleanup

Only one PR should remain open:

- PR #22 — optional stdio MCP server — **draft / parked**

The former stacked substrate PRs and the recovered adversarial PR are closed
because their accepted work is now in `main`.

## Development rule after this audit

1. Start new engineering work from current `main`.
2. Use a short-lived feature branch only for a real review/experiment boundary.
3. Run normal tests plus recursive self-analysis before merge.
4. Merge or explicitly discard the branch when the checkpoint ends.
5. Never resume implementation from a historical S-stage or V2 archive branch.
6. A historical branch with a useful idea should create a current-main backlog
   item or fixture; the branch itself is not the roadmap.

This audit is the pre-Rust fragmentation checkpoint.
