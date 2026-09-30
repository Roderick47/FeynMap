# P2.2 — Independently preauthored channel-budget comparison

**Status:** Benchmark and diagnosis complete (29 September 2026).
**Decision:** Do **not** make the P2.1 role-aware packer the default. Lower
estimated context is not equivalent to delivering enough task evidence.
P2.3 must repair selection/sufficiency *without gold-label lookup*, validate
the correction on a newly frozen comparison, and only then evaluate actual
downstream answer fidelity.

## Reproduction and source/oracle integrity

The fixture corpus was committed **before its retrieval results were
observed** and locked as
`experiments/p2_2_delivery_manifest.json` (Git blob
`13595728204cf2bac4cd4242ec6217654ee59cab`).
The runner hard-rejects any changed manifest or source-file blob. It also
checks that every named expected symbol really appears in the frozen source
with Python's independent standard-library AST, rather than trusting
FeynMap's graph as its own truth oracle.

Two explicitly different cohorts:

- **Five new stockroom development tasks**, from
  `experiments/fixtures/p2_channels/`: cross-file negative-stock validation,
  a necessary regression test, opening-stock migration, migration-specific
  test, and reorder-rule implementation. Source-authored irrelevant pricing,
  extra migration, extra tests and generated vendor symbols are labeled
  individually as distractors. The migration test intentionally uses a
  dynamic import so static evidence is not silently overstated.
- **Three separate symbol-level DRF calibration queries**, against the
  existing pinned public commit
  `b578eab1cad040414b758131af1e17aa000b51e2`. Blob identities of
  `serializers.py`, `fields.py`, `throttling.py` and
  `tests/test_throttling.py` are pinned too. DRF's repository/revision has
  been used in P1 and is **not an unseen held-out cohort**; these questions
  test finer-grained source symbols than P1's file-level probes.

Each task performs exactly **one S2 activation**, then passes the identical
activated result to three S3 packing arms, each tested under a tight
1,600-token / 12-node / 12-edge budget and a standard
3,200-token / 24-node / 24-edge budget:

| Arm | Implementation-file floor | Non-test task's incidental test-node limit |
|---|---:|---:|
| Legacy default | Existing legacy behavior | Existing legacy behavior |
| P2.1 role-aware (opt-in) | 2 distinct source files, if activated | 35% |
| Pre-registered balanced variant (opt-in) | 1 source file | 50% |

The policy never receives any `required_files`, `required_symbols`,
optional support or distractor labels while choosing context. Those labels
are inspected **after** all three delivery results exist. The analyzer,
stored graph and original P1 source-authored oracle are not modified.

## What is actually measured

For every required file **and** unique path-qualified function/class symbol,
report whether it was *not indexed*, *not activated*, *activated but
omitted*, or *delivered*. Distinguish file recall from granular symbol recall,
and report recall conditional on actual activation. Required test/migration
evidence is scored as essential when the source-authored task asks for it;
tests are never universally classified as noise.

The model-facing `estimate_tokens` is FeynMap's deterministic compact-JSON
character-count/4 heuristic. The evaluator attributes the exact encoded
**node character** lengths to implementation/test/migration/vendor/etc.;
common JSON structure, separators, anchors and edges remain explicit
non-node overhead. Every character reconciles to the complete serialized
payload before the heuristic is applied. Individually preauthored distractor
nodes have their own approximate char/4 equivalents. These figures are
**not** measured provider tokenizer costs, and unrelated-but-unlabeled
nodes are **not** automatically called distractors.

The collector independently re-verifies every budget, each activated node
and source edge endpoint, scored required symbol outcome, per-channel count
and exact common-versus-node accounting. Failed source/oracle or accounting
integrity hard-fails CI. A policy that drops known evidence instead produces
a clearly marked **measured_with_policy_regressions** report—it does not
rewrite the source labels to report success.

## Measured findings: standard budget

Replay:
[GitHub Actions run 36555370204](https://github.com/Roderick47/FeynMap/actions/runs/36555370204),
with full source-specific and combined JSON artifacts. Every one of the
preauthored required **10/10 stockroom symbols and 7/7 DRF symbols** was
successfully activated, so this experiment isolates a *delivery* gap.

| Cohort | Packing policy | Required files delivered | Required symbols delivered | Required test symbols | Required migration symbols | Mean estimated context tokens |
|---|---|---:|---:|---:|---:|---:|
| Stockroom (5 tasks) | Legacy | 10/10 | **10/10** | 2/2 | 2/2 | 1,787 |
| Stockroom | Role-aware P2.1 | 9/10 | **5/10** | 1/2 | 0/2 | 839 |
| Stockroom | Balanced floor 1 | 8/10 | **4/10** | 1/2 | 0/2 | 817 |
| DRF calibration (3 queries) | Legacy | 5/5 | **6/7** | 0/1 | n/a | 2,373 |
| DRF | Role-aware P2.1 | 4/5 | **4/7** | 0/1 | n/a | 875 |
| DRF | Balanced floor 1 | 5/5 | **5/7** | 0/1 | n/a | 880 |

For the **tight** budget, legacy stockroom delivers 9/10 required symbols,
versus 5/10 for P2.1 and 4/10 for balanced. In DRF, the tight-budget scores
are 3/7 legacy, 4/7 P2.1, and 5/7 balanced. Thus the better arm depends
on the task and budget: it is not defensible to call one a universal winner.

The collector records **31 label-regression occurrences** across the two
experimental policies and budgets; these are repeated file/symbol losses
across specific policy/budget combinations, **not 31 unique erroneous
relationships or 31 user failures**.

### Mechanism illustrated by the individual source traces

- In the negative-stock implementation task, `validate_adjustment` is
  activated but left out by source-first; legacy includes it.
- In the opening-stock migration task, role-aware includes both required
  **files** but delivers neither `apply_opening_stock` nor
  `stock_default_value`. File-level success would hide a 0/2 symbol result.
- The corresponding migration regression test loses its specifically
  required test method and migration entrypoint, although both were
  activated. Merely recognizing the word "test" is not enough.
- In a new DRF serializer question, P2.1 may deliver `serializers.py`
  without the activated `fields.Field`; balanced delivers both. This
  does not negate the successful original P2.1 *different* serializer query.
- In throttling, the activated `SimpleRateThrottle.wait` implementation
  method is missed by both experimental arms, while the legacy standard
  context retains it.
- The activated `SimpleRateThrottleTests` class is omitted by **all three
  standard-budget arms**, even when `tests/test_throttling.py` appears in
  the delivered file list. This is a baseline deficiency too, not a
  role-aware-only regression.

Source-first also reduces named distractor equivalents across the stockroom
tasks (approximately 712 → 319 in aggregate char/4 terms), but its loss of
required source/test/migration evidence is materially distinct from removing
irrelevant code. The comparison says **do not optimize token counts alone**.

## Diagnosis and next experiment

The P2.1 policy reserves a *file representative* per channel and often marks
its small set of critical nodes sufficient around the initial 900-token cap.
An activated file or class is not proof that the method answering the task
has been delivered. Simply changing the implementation floor from two to
one and the incidental test cap from 35% to 50% did **not** repair that.

**P2.3a design hypothesis, not a measured claim:** use task-relevant
symbol witnesses, source-proven cross-file behavioral continuations and
intent-specific necessary test/migration evidence to decide context
sufficiency. Keep the graph source truth and independent budget guard
unchanged. Do not read development gold labels during selection. Freeze
new cases before tuning/evaluating the correction rather than claiming
an unbiased gain by fitting P2.2's observed misses.

**P2.3b:** compare actual downstream answer/claim fidelity, missing evidence,
extra context requests and cost before selecting a default. Preserve an
entirely separate disjoint sealed S7 agent-repair set for task-level
outcome claims. The accepted conclusion of P2.2 is **a valid, reproducible
negative comparison for unconditional source-first delivery**, not a
general claim about hallucination reduction or external accuracy.
