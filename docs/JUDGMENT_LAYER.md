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
