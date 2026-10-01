# P2.4b — fresh source-locked behavioral evidence comparison

P2.4a introduced an opt-in task-conditioned behavioral envelope after P2.3b showed that correct files and correct symbols can still be insufficient for behavioral questions. P2.4b asks a narrower question on a **fresh corpus authored before the evaluator existed**:

> Does the already-implemented deterministic P2.4 behavioral layer expose materially more task-required source evidence than P2.3a `symbol_evidence` alone, without losing explicit unknowns or breaking the fixed evidence budget?

This checkpoint measures **evidence availability**, not downstream model-answer correctness.

## Freeze chronology

P2.4b branches from merged P2.4a commit `ca7aca2c4eccfb052795a1b08d683dfccefc2510`.

A new billing/invoice-settlement fixture was authored under `experiments/fixtures/p2_4b_billing/`. It contains Python implementation, tests and migration behavior plus JavaScript formatting behavior. The fixture source was complete at commit `738b7d46767f9060851ea5545317a0fe9759cc43`.

The scoring oracle was then committed as `experiments/p2_4b_behavior_manifest.json` **before `feynmap/p2_4b_evaluate.py` existed and before any P2.4b replay**. Its immutable Git blob is:

`5900e1f64cb482a720cb12ad7fd87d0ccb176172`

The manifest preregisters seven tasks: six answerable tasks with **15 atomic behavioral evidence patterns** and one deliberately nonexistent `capture_card` control. Gold patterns and support symbols are scoring-only.

The evaluator uses a two-pass protocol:

1. build all sparse and behavioral packets using only each task's natural-language query;
2. only after all packets exist, read the preregistered patterns and score the already-produced model-facing payloads.

The deterministic behavior arm is built from the **exact same P2.3a `symbol_evidence` context** as the symbol-only arm. It does not rerun activation with gold information.

## Harness-only pre-score correction

Workflow run `36780529363` did not produce a P2.4b score. The evaluator reached result assembly and raised `NameError` because JSON-style `false` appeared in Python source instead of `False`.

The only change before the first completed score was that boolean typo. The source fixture, frozen oracle, graph construction, activation, symbol delivery, behavioral extraction, deterministic relevance and packing were unchanged. This is recorded as a harness correction rather than a substrate tuning iteration.

## First completed fresh result

Canonical first completed replay:

- workflow run: `36780685329`
- evaluated head: `e92d173b363fd1a6f21ed01daf3460d316ccb42d`
- result artifact: `p2-4b-fresh-result`, artifact ID `11127114242`
- artifact ZIP SHA-256: `a50e5c431a624aaffc3f80329920625b2b69279c223c714263bcdaa8bfbeeeba`

| Arm | Required patterns exposed | Recall |
| --- | ---: | ---: |
| P2.3a `symbol_evidence` | **1 / 15** | **6.7%** |
| P2.4 deterministic behavior | **13 / 15** | **86.7%** |

The preregistered representation gate passed:

- aggregate behavioral-pattern recall improved;
- no task had lower behavioral-pattern recall than its symbol-only packet;
- nonexistent `capture_card` remained explicitly unresolved/insufficient and was not invented;
- every behavioral packet stayed within the fixed **2,200 estimated-token behavioral cap**.

Across all seven tasks, the deterministic behavioral envelope averaged about **2,114.71 estimated tokens**. Sparse + behavioral context averaged about **3,162.14 estimated tokens**. These are FeynMap's compact-JSON `ceil(chars/4)` estimates, not provider tokenizer or billing counts.

## Task-level result

| Task | Symbol only | P2.4 behavior | Notes |
| --- | ---: | ---: | --- |
| `apply-payment-implementation` | 0/4 | **4/4** | validation call, decrement, paid-on-zero mutation and return evidence available |
| `overpayment-regression-test` | 0/2 | **1/2** | state-preservation test evidence available; one condition/error pattern remains missing |
| `exact-payment-test` | 0/2 | **2/2** | zero balance, paid status and exact returned reference available |
| `grace-days-migration` | 0/3 | **3/3** | guard, default 7 and preservation of 14 available |
| `retry-policy` | **1/2** | **1/2** | status evidence available; explicit `retry_payment -> can_retry` return/delegation pattern remains missing |
| `javascript-payment-label` | 0/2 | **2/2** | normalization chain and template-label behavior available |
| `missing-capture-card` | n/a | n/a | `capture_card` unresolved; both sparse and behavioral result remain insufficient |

## Preserved misses

Two of the 15 preregistered patterns were not present in the deterministic behavioral packet:

1. `overpayment-condition-and-error` for `overpayment-regression-test`;
2. `delegates-can-retry` for `retry-policy`.

P2.4b deliberately **does not repair and rescore** these misses. Doing so after observing the frozen result would turn this corpus into another tuning set.

Their root cause is therefore left as a post-hoc diagnostic question. A later development slice may determine whether each miss comes from upstream activation, S3 symbol delivery, behavioral extraction, task relevance selection or the bounded packer. Any resulting fix must be evaluated on another fresh set rather than retroactively changing this checkpoint's 13/15 result.

## Provider-backed relevance

The manifest includes an optional provider-backed relevance arm, but it was **not run**. No real `JudgmentProvider` and model identity were explicitly configured for this replay, so P2.4b does not substitute a mock judge and call that model evidence.

A future Jev/Laya/Jeff-style comparison should receive the same extracted candidate observations and should be evaluated separately for retained required evidence, uncertainty behavior, context cost and eventual downstream answer fidelity.

## What P2.4b establishes

On this fresh synthetic source-locked corpus, the already-implemented deterministic P2.4 layer makes substantially more preregistered task-required behavioral evidence available to a downstream model than symbol-only delivery: **13/15 versus 1/15**, while preserving the explicit missing-identifier control and the fixed behavioral budget.

This supports the architectural direction:

`source truth -> sparse symbols -> source-backed behavior -> task relevance -> bounded evidence -> downstream judgment`

It also confirms that the P2.3b failure was not simply solved by sending larger files. The gain comes from exposing source-backed behavioral facts and witnesses attached to selected symbols.

## What P2.4b does not establish

P2.4b does **not** establish:

- that an LLM will correctly answer 86.7% of tasks;
- a production hallucination-reduction percentage;
- superiority of learned relevance over deterministic relevance;
- provider token/cost savings;
- a reason to switch the legacy product default immediately.

The corpus is fresh relative to P2.4a implementation but is still a small synthetic in-repository corpus. S7 remains separately sealed and unused.

## Decision and next checkpoint

The **fresh behavioral representation gate passes**, but the legacy product default remains unchanged.

Next work should be separated into two tracks:

1. **Development diagnostics:** classify the two preserved P2.4b misses without changing this result; if fixes are warranted, implement them as a later development slice and evaluate them on another fresh corpus.
2. **Downstream validation:** use a new preauthored answer-fidelity set or the appropriate independently sealed S7 stage to test whether the richer behavioral packets actually improve grounded model answers, unsupported-claim behavior and task outcomes. A real Jev/Laya/Jeff-style relevance arm can then be compared on the same candidate evidence rather than assumed to help.

Machine-readable checkpoint: `experiments/results/p2_4b_20261001_fresh_behavior.json`.
