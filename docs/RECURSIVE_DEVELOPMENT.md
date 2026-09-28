# Recursive development protocol

FeynMap should improve itself by using the current FeynMap implementation as
part of the development loop. This is a project discipline, not a claim that
normal source inspection is forbidden.

The purpose is to make real FeynMap development continuously generate evidence
about FeynMap's usefulness as a code-understanding substrate.

## Authoritative development line

To avoid fragmented work, substrate development has one authoritative
integration line at a time.

Current integration branch:

```text
feature/tool-space-routing
```

Earlier S0-S5 branches are historical checkpoints/ancestors of this branch, not
parallel implementations. New substrate checkpoints should continue on the
authoritative integration line unless work is intentionally isolated as an
experiment with an explicit merge/discard decision.

After the current substrate line is consolidated into `main`, `main`
becomes the authoritative baseline and future feature branches should remain
short-lived.

## Required recursive loop

Every material substrate change should follow this loop:

```text
current FeynMap
      ↓
self-analysis / sparse retrieval over FeynMap
      ↓
identify task-relevant code and current blind spots
      ↓
implement the smallest justified change
      ↓
normal regression tests
      ↓
FeynMap analyzes itself again
      ↓
compare quality / context / performance evidence
      ↺
```

The recursive loop complements normal engineering evidence. It does not replace
unit tests, integration tests, profiling, code review, or direct source
inspection.

## Mandatory gates

A material checkpoint is accepted only when:

1. the authoritative branch is identified before editing;
2. FeynMap's self-hosting architecture gate passes;
3. ordinary regression tests pass;
4. any task-specific benchmark/conformance gate for that phase passes;
5. a FeynMap retrieval/self-analysis miss that required broad manual fallback is
   treated as product evidence rather than silently ignored;
6. changes do not fabricate graph relationships merely to improve self-hosting
   scores.

The invariant uncertainty rule remains:

> Missing evidence may remain unresolved. Ambiguous evidence must not be turned
> into a confident relationship merely to improve a benchmark.

## Manual fallback is a measured signal

Direct GitHub/source inspection remains allowed and necessary, especially while
FeynMap is still developing. The important distinction is whether FeynMap
provided sufficient context first.

When manual inspection discovers essential context that FeynMap omitted, that
case should be captured as one of:

- a golden architecture relationship;
- a retrieval/context benchmark case;
- an adversarial fixture;
- a parser/resolution regression case;
- a performance or contract-conformance case.

The long-term product metric is not "zero manual inspection." It is a declining
rate of manual fallback caused by missing or misleading FeynMap context.

## Recursive evidence to retain

Where applicable, each phase should preserve:

- essential-context recall;
- graph/region/node touch ratios;
- delivered context tokens;
- active-state reuse;
- tool-schema reduction;
- self-hosting architecture gates;
- unresolved/ambiguous relationships;
- latency/profile changes;
- contract/conformance results.

These measurements let FeynMap(n+1) be compared against FeynMap(n) rather than
relying on subjective impressions.

## CI enforcement

The normal test matrix continues to run all unit/integration tests. A dedicated
`recursive-self-check` CI job also runs FeynMap against the FeynMap repository,
checks the invariant self-hosting quality gates, and uploads the report as an
artifact.

A green recursive self-check means the known architecture invariants remain
grounded. It does not prove that retrieval quality or performance improved;
phase-specific benchmarks remain responsible for those claims.

## Branch discipline

Use a new branch only when at least one of the following is true:

- the work is an isolated experiment that may be discarded;
- the work must remain independently releasable;
- the change cannot safely coexist with the current integration line;
- a review boundary materially benefits from isolation.

Do not create a new branch merely because a numbered S checkpoint begins.
Sequential checkpoints should remain on the authoritative integration branch.

Before deleting historical branches, verify whether they contain commits not
reachable from the authoritative line. Unique work must be explicitly merged,
reimplemented, archived, or intentionally discarded.

## Current recursive-development status

FeynMap already has:

- a checked-in golden architecture;
- `feynmap self-check`;
- self-hosting regression tests;
- S1-S4 recursive retrieval/context benchmarks;
- S6 performance profiling against its own repository;
- S6 contract-conformance fixtures for future cross-runtime implementations.

This protocol formalizes those pieces as the default development discipline for
subsequent work.
