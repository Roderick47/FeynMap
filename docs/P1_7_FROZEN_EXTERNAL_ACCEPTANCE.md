# P1.7 — Frozen external replay and acceptance

**Question:** On three independently pinned *known development* repositories,
does P1.1 -> P1.6 recover the original source-authored relationships without
regressing accepted truths, inflating evidence tiers, inventing targets or
silently marking activation as delivery?

This checkpoint adds a read-only evaluator and CI gates. It does **not** add
framework parser rules, fabricate relationships, modify the frozen oracle,
retune the context packer or declare FeynMap generally validated on unseen
tasks.

## Immutable oracle, not self-scoring

`experiments/p1_external_framework_manifest.json` (P1.1a) contains three
specific repositories at full immutable SHAs and 11 original positive
expectations. The baseline
`experiments/results/p1_1b_20260929_external_baseline.json` is the archived
initial **2/11** measurement. The P1.7 comparator validates the Git blob SHA
of both original files **before parsing reports**, so silently editing either
file to create an artificial improvement hard-fails CI.

Every replay checks out each public repository at the manifest's exact
commit and verifies the actual checkout SHA. Their dependencies are *not*
installed, imported or executed; only FeynMap statically analyzes their
source. P1.7 independently downloads all three fresh JSON reports and
compares their identities, exact source-authored probe IDs, labels, statuses
and raw observations to both frozen inputs. Analysis errors, missing or
duplicate reports, changed expected labels and scored/observed mismatches
fail the checkpoint.

`feynmap/p1_replay_acceptance.py` writes a durable, machine-readable
`p1-7-acceptance.json` and human-readable `p1-7-summary.md`. It also writes
an explicit failed artifact in the case of broken or altered oracle inputs.

## What is compared

- For **each** of the original 11 positive probes: original status,
  current status, retained/recovered/regressed/still-unmet classification,
  original label and the actual source evidence.
- MDN model and explicit template relationships require one grounded edge
  at the **supported** tier. Framework default-template conventions require
  the **inferred** tier; a high raw confidence does not promote convention to
  runtime verification. The static named URL `books` must retain the
  actual registration source file/line and composed `/catalog/books/` path.
- Microblog requires the exact static Blueprint declaration, registered
  prefix, source decorator location and method for POST and DELETE on
  `/api/tokens`; its raw `/tokens` fragment must not be separately exposed.
- DRF retains throttling implementation retrieval and skips both real
  minified vendored JavaScript assets. The serializer query must activate
  both implementation-bearing files via the explicit
  `SerializerMetaclass._get_declared_fields -> fields.Field` source fact.
  The actual delivered context, not activation, decides the original P1.1
  serializer recall probe.
- The P1.3 structural membership count remains 29 MDN / 20 DRF,
  **zero** synthetic AppConfig dependency-hub edges; actual MDN Book impact
  and AppConfig locality isolation remain gated.
- Unmatched integration contracts reconcile to the newer diagnostic
  classification. An unreferenced server endpoint, unresolved Python builtin,
  external peer or unknown dynamic declaration is *not* automatically a
  broken graph relationship.
- Both before and after reports preserve node and edge counts, analysis
  milliseconds, process peak RSS, raw unmatched integrations and selected
  context. Essential-file **activation** and **delivery** are reported
  separately alongside the actual query budget and context channel counts.
  These are descriptive **single-run** measurements, not repeated-sample
  speed claims. Extra graph edges are not automatically true positives.

## Positive versus negative evidence

The P1.1 source-authored oracle contains **11 positive labels only**. Recovery
may be called "met positive expectations" (baseline 2/11, accepted P1.6
checkpoint 10/11), but it cannot establish a broad precision, false-positive
count, hallucination rate or successful agent-repair rate. The acceptance
JSON deliberately puts `false_positive_count: null` and
`false_positive_rate: null`, explaining why they cannot be measured with
this corpus.

Synthetic negative regression cases independently enforce:
unrelated same-name imports, dynamic/ambiguous model/serializer/route/
permission values, unregistered Flask Blueprints, unmounted DRF routers,
missing core Field usage and incorrect endpoint fragments. These establish
that the documented false-edge examples did not regress; they do not estimate
population-level false positives. Frozen S6 contract conformance and CLI
integrity/error paths are included in both Python 3.8 and 3.12 gates.

The accepted DRF issue is intentionally **not** hidden. A pinned
`rest_framework/fields.py` implementation is now *activated* but remains
outside the **delivered** 3,200-token/24-node context for the original
serializer question. It is still scored as the one unmet positive probe.
Implementation-versus-test allocation policy belongs to P2, not an
unjustified extra P1 graph edge. A later real delivery fix must update
the measured result rather than rewrite the frozen oracle.

## Reproduction

The existing `p1-external-semantic-baseline` GitHub Actions matrix produces
`p1-<fixture>.json` for each pinned source. Its collection job now invokes:

```bash
python feynmap/p1_replay_acceptance.py \
  --manifest experiments/p1_external_framework_manifest.json \
  --baseline experiments/results/p1_1b_20260929_external_baseline.json \
  --reports-dir collected \
  --output p1-7-acceptance.json \
  --markdown p1-7-summary.md \
  --analyzer-revision "$GITHUB_SHA"
```

Two independent `p1-acceptance-conformance` jobs (Python 3.8 and 3.12)
exercise frozen S6 contract fixtures, error paths, original P1.1 probes,
P1.7 comparison/tamper scenarios and all P1.2–P1.6 source-negative suites.
The regular full test workflow additionally runs both Python versions and
recursively self-analyzes FeynMap, with the existing quality gates.

The P1.1–P1.7 cases are a **known development regression set**. S7 requires
a genuinely new, independently specified, sealed agent-task dataset from
different repository/tasks with oracle labels written before tool output
is inspected. No S7 performance claim or held-out result is implied here.
