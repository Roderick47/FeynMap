# Judgment providers and Jev

FeynMap's judgment layer adds bounded probabilistic decisions without changing canonical graph truth.

## Separation of concerns

FeynMap evidence and external judgments answer different questions:

- confidence_tier and detector confidence describe how a stored graph fact is supported by evidence.
- a judgment probability describes a provider's answer to one bounded question about supplied state.
- provider confidence for Choice/Score describes how concentrated that provider's answer distribution is.

A provider must never overwrite SemanticNode.confidence, SemanticEdge.confidence, or their evidence tiers.

## Provider-neutral contract

Use JudgmentQuestion and JudgmentProvider from feynmap.judgment. Questions are atomic and share one state payload. The contract supports:

- noul: yes/no probability
- choice: one option from a closed set plus probabilities/confidence
- score: a position on an ordered rubric plus probabilities/confidence

build_judgment_state(...) converts an existing grounded context bundle into compact provider-neutral state. It preserves FeynMap evidence metadata and reports context omissions so a provider is not led to treat missing context as false.

## Jev 1.13 provider

The TypeSafe SDK currently requires Python 3.10+. FeynMap's core remains dependency-free and supports its existing Python range, so Jev is optional:

~~~bash
pip install -e ".[jev]"
export TYPESAFE_API_KEY="..."
~~~

The provider pins jev-1.13.0 by default rather than using the moving jev-latest alias. This is deliberate: benchmark and calibration results must not silently change when a new model release appears.

~~~python
from feynmap.judgment import JevJudgmentProvider, JudgmentQuestion, build_judgment_state

bundle = stored_context.context_bundle("Price.confirm_accuracy", depth=2)
state = build_judgment_state(
    "Fix the stale-price confirmation bug",
    bundle,
)

questions = {
    "relevant": JudgmentQuestion.noul(
        "Does candidates contain code relevant to task.description?"
    ),
    "best_candidate": JudgmentQuestion.choice(
        "Which candidate is most relevant to task.description?",
        {
            candidate["id"]: candidate.get("qualified_name") or candidate.get("name")
            for candidate in state["candidates"]
        },
    ),
    "need_more_context": JudgmentQuestion.noul(
        "Given root, candidates, relationships, and omissions, is more context likely needed before deeper reasoning?"
    ),
}

result = JevJudgmentProvider().evaluate(state, questions)
print(result.to_dict())
~~~

## Integration policy

The first Jev experiment should remain downstream of deterministic retrieval:

~~~text
repository -> FeynMap graph -> deterministic candidate subgraph -> Jev judgments -> policy/ranking -> coding agent
~~~

Do not send the whole repository to Jev and ask it to reconstruct graph structure. FeynMap should continue to perform structural traversal, counting, reachability, and evidence handling. Jev should make small semantic judgments over already-reduced state.

Jev questions sharing a state should normally be batched into one provider call. The TypeSafe API evaluates them independently, which makes speculative fan-out suitable for FeynMap dimensions such as relevance, likely fault-path membership, sufficiency of evidence, and whether more context is needed.

## Context Ranker experiments

The benchmark ladder now separates retrieval, ranking, transitive necessity, and external-repository generalization.

- v1A is the synthetic ranking sanity check.
- v1B uses real FeynMap graph retrieval.
- v1E freezes the direct, naive, and adaptive semantic-frontier strategies and tests transitive necessities.
- v1F keeps the v1E frontier and Jev prompt frozen, then evaluates historical change localization on Wikonomi V2.

### v1F: historical Wikonomi V2 generalization

v1F uses five real merged Wikonomi V2 changes (PRs 147-151). Each task is analyzed at a pinned revision from before the fix. The task text contains only the user-visible problem; implementation details from the eventual patch are excluded.

Production files changed by the later patch are the hidden file-level ground truth. If a changed file did not exist in the pre-fix snapshot, v1F records it as a novel target rather than a retrieval failure. Candidate symbols are deduplicated to file-level context for scoring, while the underlying semantic-node provenance is retained.

The archived revisions are given deterministic synthetic Git metadata before snapshot capture, so repository identity and snapshot IDs do not depend on the machine's temporary directory.

Run against a local Wikonomi V2 checkout:

~~~bash
python -m feynmap.judgment.context_ranker_v1f /path/to/wikonomi-v2 --pretty
python -m feynmap.judgment.context_ranker_v1f /path/to/wikonomi-v2 --jev --pretty
~~~

A single historical task can be isolated with:

~~~bash
python -m feynmap.judgment.context_ranker_v1f /path/to/wikonomi-v2 --task wikonomi-price-accuracy --pretty
~~~

Primary v1F measures include file precision/recall and NDCG at k, average precision, full-recall minimum k, context-file ratio, noise at k, path-backed recall, candidate count, compact path-state tokens, Jev latency, and provider token use.

The comparison remains:

1. direct behavioral context,
2. naive bounded behavioral expansion,
3. frozen adaptive semantic-frontier expansion,
4. frozen adaptive frontier plus Jev reranking.

A later benchmark can add a frontier-LLM judge and downstream coding-agent completion, but v1F should be interpreted before tuning the frontier or Jev prompt to Wikonomi.


### v1G: framework composition and deterministic graph identity

v1G does not change the frozen v1F task descriptions, pinned revisions, candidate
budgets, adaptive frontier policy, or Jev prompt. It changes FeynMap itself in
response to the structural misses exposed by v1F.

The phase adds:

- order-independent snapshot graph identity for semantically unordered node,
  edge, evidence, diagnostic, framework, and unresolved-integration collections;
- Django-template composition edges for static `{% extends %}` and
  `{% include %}` references;
- Django template-tag library and custom-filter dependencies from templates
  into Python `templatetags/` modules and filter functions;
- Django handler-to-`AppConfig` lifecycle dependencies based on the nearest
  application package boundary; and
- per-candidate judgment probabilities in v1F output, without changing the
  frozen relevance question or reranking policy.

Historical snapshots remain load-compatible: stored graphs written with the
legacy raw-JSON hash are accepted during verification, while newly captured
snapshots use the order-independent graph identity hash.

The primary v1G validation is a strict before/after rerun of the unchanged v1F
spec. Improvements should come from newly available semantic paths rather than
benchmark retuning. In particular, the expected newly representable Wikonomi
paths include:

~~~text
view -> rendered template -> extended base -> loaded JavaScript
view -> rendered template -> included partial
view -> rendered template -> template-tag library / custom filter
Django handler -> app AppConfig
~~~

The changed-file ground truth remains intentionally conservative. A changed
supporting file may not be structurally necessary for the task root, so raw
changed-file recall should be reported alongside path-backed recall rather than
treated as exhaustive semantic relevance.

### v1J: repair-role judgment

v1J is a new experiment, not a revision of v1I. It leaves v1I's historical
Wikonomi retrieval, prompt, and metrics unchanged. Its fixture corpus is
independent of the five frozen historical tasks, so the role vocabulary and
questions are not tuned against their outcomes.

The experiment separates two questions that a single relevance probability
conflates:

1. Does this symbol or region materially help understand, implement, or validate
   the repair?
2. What role does it play: `implementation_target`, `structural_bridge`,
   `supporting_context`, or `incidental_context`?

An implementation target is a region whose behavior or data definition must
change. A structural bridge connects the task entry point to relevant behavior
but is not itself an edit target. Supporting context supplies constraints or
validation. Incidental context is retrieval noise. Structural bridges and
supporting context are therefore semantically relevant without being repair
targets.

The checked-in corpus contains four synthetic tasks and sixteen labeled source
regions. Every task contains all four roles. Candidate state includes compact
summaries, excerpts, region spans, and generic relationship names; it contains
no gold labels, language rules, framework rules, or Wikonomi examples.

Validate the fixtures without making a provider call:

~~~bash
python -m feynmap.judgment.repair_role_v1j --pretty
~~~

Run the live Jev experiment:

~~~bash
python -m feynmap.judgment.repair_role_v1j --jev --pretty
~~~

Use `--task TASK_ID` to isolate one fixture or `--spec PATH` to evaluate another
corpus with the same schema. v1J reports semantic-relevance accuracy, Brier
score, and log loss; repair-role accuracy, macro F1, per-role scores, and a
confusion matrix; and implementation-target MRR and recall at 1 and 3. The
target ranking uses implementation-target probability first and relevance only
as a tie-breaker, so a highly relevant bridge cannot outrank a likely edit
target merely because both are useful context.

### v1K: adversarial repair-role generalization

The first live v1J run correctly classified all implementation targets,
structural bridges, and supporting context. Its only role error narrowly called
an incidental persistence operation supporting context, while the independent
relevance probability still correctly remained below 0.5. v1K turns that
observation into generic evaluation improvements without changing the frozen
v1J questions or using the Wikonomi tasks.

The v1K corpus adds:

- opaque `region_*` candidate identifiers;
- identical candidates whose roles change under two different task requests;
- a repair requiring two implementation regions in the same file;
- a suspicious-looking structural bridge that must remain unchanged;
- forward and reversed candidate-order controls;
- full-relationship and relationship-ablated controls; and
- optional repeated provider runs for stability measurement.

In addition to v1J's calibration, classification, and target-ranking metrics,
v1K reports role-probability margin and entropy, low-margin decisions,
relevance/role disagreement, error confidence, task-conditioning accuracy,
order invariance, relationship-ablation sensitivity, and repeated-run
stability. Comparison metadata and gold labels are never included in provider
state.

Validate the adversarial fixture corpus without a provider call:

~~~bash
python -m feynmap.judgment.repair_role_v1k --pretty
~~~

Run one live evaluation with the unchanged v1J prompt:

~~~bash
python -m feynmap.judgment.repair_role_v1k --jev --pretty
~~~

Measure live judgment stability across three complete runs:

~~~bash
python -m feynmap.judgment.repair_role_v1k --jev --repetitions 3 --pretty
~~~

The repeated form costs three times as many provider calls and should be used
after a single run confirms that the fixture and credentials are working.

Control tasks intentionally repeat the same semantic case with one variable
changed. v1K therefore reports both raw metrics over every provider call and a
`control_adjusted` summary that retains one representative from each order and
relationship control pair. Task-conditioning pairs remain separate because the
task request legitimately changes their gold roles. This prevents duplicated
controls from silently overweighting aggregate classification scores.

Diagnostics include task-qualified role and relevance error records with source
regions, predicted and gold roles, relevance probability, and role margin. For
multi-target tasks, `implementation_target_task_hit_rate@1` answers whether the
first result is any valid edit target, while fractional recall at 1 continues to
measure how much of the complete edit set fits in the first slot.

### v1L: ambiguity-aware repair-role adjudication

The control-adjusted live v1K run classified 25 of 27 primary role labels
correctly and placed a valid implementation target first for every task. Both
remaining misses were non-target boundary cases: unchanged behavior explicitly
mentioned by the task was judged useful context even though its strict fixture
label was incidental. This is evidence to improve evaluation, not evidence to
rewrite v1K labels or tune its prompt after seeing the result.

v1L is therefore a new experiment with a new synthetic corpus. It keeps the
v1J relevance and role questions unchanged and predeclares, before any provider
run:

- one primary relevance/role label for strict comparability;
- a bounded set of acceptable joint relevance/role labels;
- a rationale for every label; and
- a named taxonomy boundary for every multi-label candidate.

The corpus contains five framework-agnostic tasks and twenty source regions,
with five primary labels for each repair role. Five non-target regions exercise
predeclared boundary cases such as a connector that also states a constraint or
unchanged behavior explicitly protected by the task. Implementation targets
are always singleton labels, so ambiguity cannot excuse a missed edit location.
Adjudication metadata and rationales are removed before provider state is built.

Validate the fixture and its leakage guards without a provider call:

~~~bash
python -m feynmap.judgment.repair_role_v1l --pretty
~~~

Run the live Jev evaluation:

~~~bash
python -m feynmap.judgment.repair_role_v1l --jev --pretty
~~~

v1L reports the original strict primary-label metrics alongside role,
relevance, and joint acceptable-label accuracy. It also reports mean probability
mass assigned to the acceptable role set and acceptable joint-label set,
separate joint accuracy for ambiguous and singleton candidates, unchanged
implementation-target ranking metrics, and full records for predictions outside
every predeclared acceptable label. Strict scores remain visible; acceptable
sets add an annotation-quality lens rather than replacing the original gold.

### v1M: offline joint-coherence analysis

The first live v1L result achieved perfect implementation-target ranking,
95% strict role accuracy, and 100% acceptance on each axis considered
separately. Its sole unacceptable joint prediction combined `supporting_context`
with semantic relevance below 0.5. Those answers are individually defensible
but jointly violate the existing taxonomy, where every non-incidental role is
semantically relevant.

v1M is an offline analysis of that failure mode. It does not call Jev, change
prompts, modify provider answers, or rewrite fixture labels. For each role it
multiplies the provider's role probability by the probability of the relevance
value implied by that role, then normalizes across the four taxonomy-consistent
labels. There are no learned weights or benchmark-tuned thresholds.

Analyze an existing v1L result:

~~~bash
python -m feynmap.judgment.repair_role_v1m path/to/v1l-result.json --pretty
~~~

The report compares raw and coherent strict/acceptable joint accuracy, counts
cross-axis disagreements, role and relevance changes, repaired predictions,
introduced regressions, and the probability mass on taxonomy-consistent labels.
It also recomputes implementation-target ranking from the coherent role
distribution. The input loader accepts UTF-8 and BOM-marked UTF-16 JSON, which
covers files written by both modern PowerShell and Windows PowerShell
`Tee-Object` defaults.

### v1N: token-budgeted shadow context assembly

v1J-v1L consistently placed every implementation target first, and v1M made
the independent relevance and role axes coherent. v1N tests how those outputs
could guide bounded context assembly without changing v1I or any production
policy. It is an offline shadow experiment over the independent v1L corpus and
makes no provider calls.

The role-aware order is deterministic and uses no gold labels:

1. anchor the candidate with the highest coherent implementation-target
   probability;
2. retain any additional predicted implementation targets;
3. reserve early positions for one supporting-context candidate and one
   structural bridge; and
4. order remaining eligible candidates by coherent non-incidental probability.

Candidate costs use FeynMap's tokenizer-independent estimator over the exact
provider-facing candidate payload. The experiment compares role-aware and
relevance-only assembly at 25%, 50%, 75%, and 100% of total candidate cost,
with every budget raised when necessary to fit the strongest target anchor.
Predicted incidental candidates are ineligible for budget backfill: a small
noise candidate is not selected merely because a larger useful candidate did
not fit. The first shadow run exposed and corrected that failure mode before
the policy was committed.

Run the shadow analysis on an existing v1L result:

~~~bash
python -m feynmap.judgment.repair_role_v1n path/to/v1l-result.json --pretty
~~~

v1N reports target recall and task hit rate, strict and acceptable relevance
recall, strict and acceptable context-role coverage, incidental and
unambiguously unacceptable selection rates, utilization, selected candidates,
and order-invariance checks. Ambiguity-aware metrics ensure that a predeclared
supporting/incidental boundary is not counted as definite retrieval noise. The
output explicitly records `production_policy_changed: false`; promotion beyond
shadow mode requires evidence outside these synthetic fixtures.

### v1O: frozen-policy historical holdout

v1O moves the already frozen role pipeline onto v1I's five historical
Wikonomi tasks as a holdout evaluation. It does not revise those tasks, their
changed-file ground truth, v1I retrieval, the relevance prompt, the v1J role
prompt, v1M coherence, or v1N assembly policy. No historical label participates
in selection or ordering.

Each task makes two deliberately separate provider requests over the same
compact grounded state:

1. the unchanged v1I relevance-only request, whose result remains the reported
   relevance baseline; and
2. a role-only request using the frozen v1J role question and criteria.

Keeping the requests separate prevents the added role questions from changing
the original relevance judgment. v1O then applies v1M coherence and v1N
role-aware ordering in shadow mode, filters predicted incidental candidates
from context backfill, and evaluates the resulting file order against the
unchanged historical changed files. The normal v1I reranked order remains in
the output and is not mutated.

Run the live holdout evaluation:

~~~bash
python -m feynmap.judgment.context_ranker_v1o /path/to/wikonomi-v2 --jev --pretty
~~~

Use `--task TASK_ID` for a bounded diagnostic run. A complete run makes ten
provider requests: five unchanged relevance calls and five role-only calls.
The report includes relevance-only and role-shadow file metrics, coherent role
probabilities per candidate, changed-file role predictions, predicted
incidental exclusions, separate usage and elapsed time for each judgment pass,
and combined token usage. `production_policy_changed` remains false regardless
of the result; promotion requires an explicit later decision.

### v1P: offline historical promotion gate

v1P turns a judged v1O report into a reproducible promote/reject decision. It
makes no provider calls, changes no ranking, and learns no weights or thresholds
from the five historical tasks. The gate requires both aggregate and per-task
non-regression in average precision, reciprocal rank, and recall at 1, 3, 5,
and 10. It also rejects a policy that makes any previously retrieved existing
changed file newly missing.

Analyze a v1O result, including UTF-8 or BOM-marked UTF-16 files:

~~~bash
python -m feynmap.judgment.context_ranker_v1p path/to/v1o-result.json --pretty
~~~

The report records metric deltas, newly missing and recovered changed files,
excluded candidates backed by changed files, and the separate and combined
judgment costs. Cost ratios are descriptive rather than tuned promotion
thresholds. A failed gate explicitly recommends retaining repair-role output as
shadow evidence and rejecting hard incidental-role filtering. Passing the gate
only makes a policy eligible for explicit review; it never changes production
behavior automatically.

### v1Q: non-destructive dual-channel guidance

The v1O holdout and v1P gate show that a repair-role prediction is not a safe
eligibility decision: files changed for configuration, presentation, or
supporting behavior can still look incidental when judged one region at a
time. v1Q tests a different architecture on the independent v1L fixture corpus
without revising its labels or using the Wikonomi tasks.

The two output channels have deliberately separate authority:

- semantic relevance exclusively orders and retains context candidates; and
- coherent repair roles provide a separate edit-target order and explanatory
  implementation, support, bridge, and incidental lanes.

Every candidate remains in the context channel. Role predictions cannot filter
or reorder it, and evaluation labels are absent from the emitted annotations.
Both channels use deterministic candidate-id tie breaking and are checked for
input-order invariance.

Analyze an existing judged v1L result without another provider call:

~~~bash
python -m feynmap.judgment.repair_role_v1q path/to/v1l-result.json --pretty
~~~

The report includes candidate retention, target MRR and recall, top-target task
hit rate, role lanes, source-region annotations, and explicit policy metadata.
It remains an offline experiment and never changes production behavior.

### v1R: historical dual-channel validation

v1R applies the frozen v1Q separation to an existing judged v1O historical
report without another provider call. The original v1I relevance file order is
copied as the context channel and its file metrics are independently recomputed.
Every numeric delta must be zero, every role-judged candidate is retained, and
role output cannot filter or reorder context.

The second channel contains a deterministic edit-target candidate/file order,
four explanatory role lanes, and role annotations. It is evaluated against
historical changed files only as a deliberately weak proxy: a changed support,
configuration, test, or presentation file is not necessarily an implementation
target. Historical labels never participate in either order.

Analyze an existing v1O result:

~~~bash
python -m feynmap.judgment.context_ranker_v1r path/to/v1o-result.json --pretty
~~~

The report fails validation if the source is not a judged v1O result and
explicitly records context-order equality, metric equality, full candidate
retention, order invariance, and `production_policy_changed: false`.
