# P2.4d — Fresh downstream validation of repaired task-conditioned evidence

P2.4d evaluates the repaired P2.4c pipeline on a new source-locked corpus. It separates two questions that earlier P2 checkpoints intentionally kept distinct:

1. **Representation:** did FeynMap deliver the source-backed behavioral evidence required by the task?
2. **Downstream fidelity:** given only that model-facing packet, did a model produce the required grounded answer without unsupported claims?

The second question requires an oracle-blind answer run before it can support any shipping/default decision.

## Freeze order

The corpus was frozen before the evaluator existed.

1. A new mixed Python/JavaScript rollout fixture was committed at `3d34727a39275576cfbff3f630bf8b1998e70a0b`.
2. The scoring oracle was then committed at `15e3c361a852c985b8a36759ddebdfe94768723c`.
3. The oracle file `experiments/p2_4d_downstream_manifest.json` has immutable Git blob `153bd1d1e0912c6b008ac8b0ba00c76c3529662e`.
4. Only after those freezes did `feynmap/p2_4d_evaluate.py` first appear, at commit `aafc7d2171af2c1d32535796887617a7a16911a4`.

The evaluator verifies the manifest blob and every source blob before constructing contexts. Gold behavior patterns, required claims, support symbols, unsupported traps and expected statuses are scoring-only. They are not supplied to activation, relevance ranking, continuation, packing or model packets.

## Corpus

The new domain is release rollout/deployment behavior. The fixture includes Python implementation, tests and a migration, plus JavaScript transformation/formatting behavior. It contains eight tasks: seven answerable behavior questions and one intentionally nonexistent `force_promote` control.

The tasks cover:

- validation before mutation;
- status changes after a rollout batch;
- exception behavior and preservation of state;
- exact-result regression tests;
- wrapper delegation and status policy;
- migration/default preservation;
- JavaScript normalization and formatting;
- nonpositive input validation;
- explicit missing-identifier handling.

The frozen oracle contains **17 required behavioral representation patterns** and **20 required downstream answer claims**.

## Arms and shared activation

Both arms use identical S2 activation parameters and the evaluator asserts that their activated hits, edges and roots are identical.

- `symbol_evidence`: P2.3a source/symbol delivery only.
- `behavior_repaired`: the same activation plus the repaired P2.4c `TaskConditionedEvidencePipeline`, deterministic relevance, grounded behavioral extraction and the bounded one-best activated-dependency continuation.

The repaired continuation is additionally checked to remain inside already-activated nodes and to add no more than one node.

## Fresh representation result

The first completed P2.4d replay was workflow run `36828061283`. It completed without a label-driven selector/extractor repair.

| Representation result | `symbol_evidence` | `behavior_repaired` |
|---|---:|---:|
| Required behavior patterns | 17 | 17 |
| Matched patterns | **0** | **16** |
| Pattern recall | **0.0%** | **94.1%** |
| Missing `force_promote` control | pass | pass |

The preregistered fresh representation gate passed:

- repaired recall is at least 0.85;
- no answerable task regressed against symbol-only delivery;
- `force_promote` remains explicitly unresolved/insufficient;
- every behavioral envelope remains within the fixed 2,200 estimated-token cap;
- the continuation stays within its one already-activated source-backed dependency contract.

### Preserved fresh miss

`oversized-batch-regression` missed one preregistered pattern: the packet did not expose the exact policy condition `batch_size > release.remaining_hosts` together with the `BatchTooLarge` behavior. The packet did contain the regression test values, the expected exception, the unchanged post-failure state and the call from `deploy_batch` to `ensure_rollout_allowed`.

This remains a **P2.4d miss**. P2.4c is not retuned against this corpus.

### Preserved continuation diagnostic

For the JavaScript rollout-label task, the single continuation slot selected `python:symbol:rollout.models.Release`, even though the required JavaScript behavior was already delivered and all JavaScript patterns passed. This cross-language continuation is irrelevant noise. It is recorded for later development rather than repaired inside P2.4d.

## Downstream answer protocol

P2.4d exports 16 oracle-free packets: eight tasks × two arms. Each packet contains only the question, delivery sufficiency, unresolved identifiers, model-facing FeynMap context, permitted evidence references and a strict answer contract.

A downstream answer must return `answer` or `need_more_context`. Every factual claim must cite a reference actually present in that packet. The scorer separately checks:

- required answer-claim recall;
- whether matched claims cite preauthored source support;
- full-task pass rate;
- unsupported-trap hits;
- invalid or uncited claims;
- correct missing-identifier abstention.

## Oracle-exposed diagnostic answer run

A GPT-5.6 Sol interactive answer run was used only to validate packet usability and the downstream scorer. Because the same interactive session had access to the source/oracle, its metadata explicitly records `oracle_exposure=true` and `eligible_for_shipping_decision=false`.

Workflow run `36828626613` reproduced the following diagnostic score:

| Downstream diagnostic | `symbol_evidence` | `behavior_repaired` |
|---|---:|---:|
| Required answer claims | 20 | 20 |
| Matched claims | **0** | **19** |
| Grounded matched claims | **0** | **19** |
| Required-claim recall | **0.0%** | **95.0%** |
| Fully passing answerable tasks | **0/7** | **6/7** |
| Unsupported trap hits | 0 | 0 |
| Invalid citations | 0 | 0 |
| Uncited claims | 0 | 0 |
| Correct missing-context control | 1/1 | 1/1 |

The only failed answerable task is `oversized-batch-regression`, matching the same evidence-availability gap exposed by the fresh representation score.

These diagnostic numbers are useful because the candidate answerer remained conservative: it did not invent the missing policy condition, and no unsupported/citation regression was required to obtain the 95% claim recall. They are **not a blind model-accuracy result**.

## Shipping/default gate

The preregistered accuracy and safety thresholds happen to be met by the repaired arm in the nonblind diagnostic except for full eligibility: 95% claim recall, 6/7 answerable tasks, zero traps, zero invalid/uncited claims and the missing control pass.

Nevertheless both downstream gates remain false because the run is oracle-exposed. The absolute guard requires an oracle-blind run with `eligible_for_shipping_decision=true`.

Therefore:

- the legacy product default does **not** change;
- `TaskConditionedEvidencePipeline` remains opt-in;
- P2.4d fresh representation validation is complete;
- P2.4d oracle-blind downstream validation remains pending.

## Next required evidence

The correct next evaluation is **not** to edit P2.4c against this corpus. Use the already-frozen, oracle-free P2.4d packets with a provider/model process that has not seen the fixture oracle or source gold. Record the provider/model identity and real usage metadata if available, then run the existing scorer unchanged.

A later P2.4e can compare deterministic relevance with a real `JudgmentProvider`-backed relevance judge (Jev or a compatible low-cost provider) on a separately appropriate evaluation boundary. No mock-provider result should be presented as learned-model evidence.

S7 remains sealed and disjoint.
