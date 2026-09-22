# R1 AI repair benchmark

The R1 harness measures whether an AI agent produces a better repair with
FeynMap, not merely whether a ranking metric improves. It is provider-neutral
and deliberately separates benchmark execution from scoring.

The benchmark layer does not choose or embed an AI provider. Its execution
adapter can invoke an explicitly configured argv command, but never through a
shell. It copies a local fixture/repository into a disposable workspace, keeps
oracle files sealed outside that workspace, applies timeouts, captures a patch,
and removes the workspace after recording the immutable result. The original
repository remains read-only from the adapter's perspective.

## Schemas

| Schema | Purpose |
| --- | --- |
| `feynmap.ai_repair_benchmark.v1` | Task requests, repository identity, frozen arms, and hidden oracles |
| `feynmap.ai_repair_agent_input.v1` | Exact oracle-free payload visible to an AI run |
| `feynmap.ai_repair_run.v1` | Content-addressed record of one completed task/arm/attempt |
| `feynmap.ai_repair_comparison.v1` | Per-arm aggregates and deltas from the unassisted arm |

The frozen arms are:

1. `unassisted`;
2. `deterministic_context`;
3. `relevance_context`; and
4. `dual_channel`.

Assisted arms require an explicit context object. The unassisted arm rejects
one. Agent payload creation recursively rejects reserved oracle keys such as
`oracle`, `gold`, `solution`, `required_tests`, and change-file labels.

## Development fixtures versus held-out tasks

`experiments/ai_repair_r1_fixture.json` contains three small independent
development fixtures for harness tests:

- bounded retry delay;
- case-insensitive header override; and
- idempotent reservation release.

Each fixture is intentionally in its failing pre-fix state and has a standalone
`verify.py`. These fixtures test the machinery; they are not evidence of model
generalization and must not become the final R1 held-out corpus.

A real held-out specification uses the same schema with:

~~~json
"evaluation_tier": "held_out"
~~~

Its repositories/tasks must be selected before observing assisted-agent results
and must not reuse the five frozen Wikonomi tasks to tune policy.

## Validate a specification

~~~bash
python -m feynmap.judgment.ai_repair_benchmark validate \
  experiments/ai_repair_r1_fixture.json --pretty
~~~

Validation checks task and repository identities, the exact arm order, unique
test IDs, alternative acceptable change sets, and required/allowed-file
consistency. Each repository identity includes a deterministic content hash and
an explicit `content_hash_policy`. The `canonical_text_lf_v1` policy normalizes
CRLF and CR to LF for UTF-8 text identity, so ordinary Git checkout conversion
does not change a benchmark. Files containing NUL bytes or invalid UTF-8 remain
byte-exact. The executor refuses to run if source content drifts from the frozen
specification under that policy.

## Generate assisted-arm context

The three assisted R1 arms now share one oracle-free context generator. It
verifies the frozen repository content hash, copies the repository into a
temporary analysis workspace, removes every sealed oracle file before FeynMap
analysis, and creates one bounded repository-wide candidate pool.

The arms differ only after that shared pool exists:

- `deterministic_context` keeps the deterministic task-text + graph-structure
  order and makes no judgment-provider call;
- `relevance_context` reranks the exact same candidates with the frozen
  semantic-relevance judgment; and
- `dual_channel` preserves that relevance order and all candidates, then adds
  the frozen non-destructive repair-role guidance as a separate edit-target
  channel.

No benchmark gold/change-set labels participate in candidate selection,
relevance ranking, or role guidance.

Generate deterministic context:

~~~bash
python -m feynmap.judgment.ai_repair_context \
  experiments/ai_repair_r1_fixture.json \
  --task bounded-retry-delay \
  --arm deterministic_context \
  --project-root . \
  --pretty
~~~

Generate relevance or dual-channel context with Jev:

~~~bash
python -m feynmap.judgment.ai_repair_context \
  experiments/ai_repair_r1_fixture.json \
  --task bounded-retry-delay \
  --arm relevance_context \
  --project-root . \
  --jev \
  --pretty

python -m feynmap.judgment.ai_repair_context \
  experiments/ai_repair_r1_fixture.json \
  --task bounded-retry-delay \
  --arm dual_channel \
  --project-root . \
  --jev \
  --pretty
~~~

Role output cannot filter or reorder the relevance context. The context artifact
records the snapshot identity, shared-pool policy, deterministic selection
diagnostics, provider/model metadata where applicable, and the candidate and
relationship bounds used for the run.

## Create agent-visible input

Unassisted:

~~~bash
python -m feynmap.judgment.ai_repair_benchmark payload \
  experiments/ai_repair_r1_fixture.json \
  --task bounded-retry-delay \
  --arm unassisted \
  --pretty
~~~

Assisted arms additionally require `--context path/to/context.json`. Context is
stored exactly and hashed into the subsequent run manifest.

## Record an immutable run

An execution adapter records an outcome object containing:

- patch presence and SHA-256;
- changed files;
- required test IDs and statuses;
- first proposed edit;
- independently reviewed unsupported claims;
- repository-search and extra-context-request counts;
- elapsed time; and
- model/provider token usage.

Create the manifest from saved agent input and outcome files:

~~~bash
python -m feynmap.judgment.ai_repair_benchmark manifest \
  experiments/ai_repair_r1_fixture.json \
  run-input.json run-outcome.json \
  --attempt 1 \
  --provider PROVIDER \
  --model MODEL \
  --started-at 2026-01-01T00:00:00Z \
  --finished-at 2026-01-01T00:05:00Z \
  --pretty
~~~

`manifest_id` hashes the complete manifest content except the ID field itself.
Changing an outcome, model, timestamp, repository identity, task, arm, or
attempt invalidates the identity check.

## Score and compare

~~~bash
python -m feynmap.judgment.ai_repair_benchmark score \
  experiments/ai_repair_r1_fixture.json run.json --pretty

python -m feynmap.judgment.ai_repair_benchmark compare \
  experiments/ai_repair_r1_fixture.json runs/*.json --pretty
~~~

Scoring reports:

- required-test pass rate;
- required-file recall;
- allowed-file precision;
- missing, unnecessary, and forbidden changed files;
- whether the first proposed edit is in an allowed file;
- oracle and strict success;
- unsupported-claim count;
- searches and extra context requests;
- elapsed time; and
- token usage.

Alternative acceptable change sets allow more than one correct implementation
shape. The scorer chooses the best matching predeclared alternative after the
run; it never sends those alternatives to the agent.

Comparison rejects duplicate task/arm/attempt records, reports whether the full
task-by-arm matrix is present, aggregates each arm, and computes assisted-arm
deltas from the unassisted baseline.

## Execute in a disposable workspace

`ai_repair_execution` supports only explicit local `fixture:` and `path:`
repository locators. It never clones a repository implicitly. The initial test
runner accepts Python argv commands only, replaces a declared verifier with its
sealed copy, sets the disposable workspace on `PYTHONPATH`, does not invoke a
shell, captures bounded output tails, and records timeout as an error.
Declared sealed files are omitted from both the baseline and agent workspaces;
only the executor-owned sealed directory contains them. This prevents hidden
verification logic from becoming agent-visible repair context.

An external agent command receives three exact placeholder paths:

- `{workspace}`: disposable repository copy that it may edit;
- `{input}`: oracle-free agent-input JSON; and
- `{output}`: JSON path the command must create with run observations.

All adapter options must appear before `--`, followed by the agent argv. For
example:

~~~bash
python -m feynmap.judgment.ai_repair_execution \
  experiments/ai_repair_r1_fixture.json run-input.json \
  --project-root . \
  --provider PROVIDER \
  --model MODEL \
  --test-timeout 60 \
  --agent-timeout 900 \
  --pretty \
  -- agent-cli --workspace {workspace} --input {input} --output {output}
~~~

The agent subprocess receives only a minimal system environment. Credentials or
other values must be named explicitly with repeated `--pass-env NAME`; FeynMap
does not forward the parent environment wholesale.

The adapter verifies that sealed oracle files remain byte-identical after the
agent returns. The disposable directory and minimal environment are safety
boundaries against accidental contamination, **not** an operating-system
security sandbox. At this checkpoint, run only explicitly trusted agent
commands. Container/OS isolation is required before executing untrusted code or
agents that are not expected to remain within the supplied workspace.

The agent output object may contain `first_proposed_edit`,
`unsupported_claims`, `repository_searches`, `extra_context_requests`, and
`usage`. The adapter supplies patch identity, changed files, baseline/final test
statuses, elapsed time, provider/model identity, and manifest identity.

The execution report also includes diagnostic output tails and the patch text.
Those diagnostics are not model input and are not used to select or order
context.

## Freeze the held-out corpus before assisted runs

A held-out R1 corpus must be locked before observing any assisted-arm result.
The freeze gate requires at least five tasks, explicit selection metadata, per-task
admission provenance, no reuse of the development fixtures or the five frozen
Wikonomi task IDs, and explicit declarations that neither solutions nor
assisted-agent outcomes were inspected before selection.

Create the lock:

~~~bash
python -m feynmap.judgment.ai_repair_holdout freeze \
  experiments/ai_repair_r1_holdout.json \
  --pretty > experiments/ai_repair_r1_holdout.lock.json
~~~

Verify the lock before running the benchmark:

~~~bash
python -m feynmap.judgment.ai_repair_holdout check \
  experiments/ai_repair_r1_holdout.json \
  experiments/ai_repair_r1_holdout.lock.json \
  --pretty
~~~

The lock hashes the complete benchmark specification plus each task description,
repository identity, oracle and admission metadata. Any later change invalidates
the lock. Once frozen, retrieval or role policy must not be tuned against that
corpus; policy changes require a new corpus/version rather than silently
re-running the same holdout.

## Real-world R1 with SWE-bench

R1 can now use real historical SWE-bench tasks while preserving FeynMap's
four-arm experiment. SWE-bench remains the authoritative repair evaluator:
official `resolved` status is the primary outcome. Reference-patch changed-file
overlap is recorded only as a localization proxy because an alternative correct
repair may legitimately touch different files.

The bridge intentionally separates selection from oracle sealing. The
`select` phase reads only instance id, repository, base commit, issue text and
version. Gold patch, test patch, hints, FAIL_TO_PASS and PASS_TO_PASS fields do
not participate in selection. The `prepare` phase may inspect the already
selected gold patch solely to seal hidden diagnostics and prepare the exact
buggy checkout.

Optional tools for this workflow are not core dependencies:

~~~bash
pip install datasets swebench
~~~

Select an eight-task Verified pilot, capped at two tasks per repository:

~~~bash
python -m feynmap.judgment.swebench_r1 select \
  SWE-bench/SWE-bench_Verified \
  --split test \
  --corpus-id feynmap-r1-swebench-v1 \
  --count 8 \
  --max-per-repo 2 \
  --output experiments/swebench_r1_selection.json
~~~

Materialize detached base-commit worktrees and freeze both the R1 spec and
holdout lock:

~~~bash
python -m feynmap.judgment.swebench_r1 prepare \
  SWE-bench/SWE-bench_Verified \
  experiments/swebench_r1_selection.json \
  --split test \
  --checkout-root .feynmap/r1/swebench/checkouts \
  --cache-root .feynmap/r1/swebench/cache \
  --output experiments/swebench_r1_holdout.json \
  --lock-output experiments/swebench_r1_holdout.lock.json
~~~

Generate all assisted contexts. One Jev relevance judgment is shared by the
relevance and dual-channel arms for each task; the dual arm adds role guidance
without changing relevance context order or retention:

~~~bash
python -m feynmap.judgment.swebench_r1 generate-contexts \
  experiments/swebench_r1_holdout.json \
  --output-root .feynmap/r1/swebench/contexts
~~~

Run one trusted command agent across the complete four-arm matrix. Arm order is
deterministically rotated per task to reduce systematic time/order bias:

~~~bash
python -m feynmap.judgment.swebench_r1 run-matrix \
  experiments/swebench_r1_holdout.json \
  --context-root .feynmap/r1/swebench/contexts \
  --output-root .feynmap/r1/swebench/runs \
  --provider PROVIDER \
  --model MODEL \
  --pass-env PROVIDER_API_KEY \
  -- agent-command --workspace {workspace} --input {input} --output {output}
~~~

The matrix writes one official prediction JSONL per arm under
`.feynmap/r1/swebench/runs/predictions/`. Grade each file with the official
SWE-bench evaluator, using a distinct run id per arm:

~~~bash
swebench eval verified \
  -p .feynmap/r1/swebench/runs/predictions/unassisted.jsonl \
  --run-id feynmap-r1-unassisted \
  -j 1

swebench eval verified \
  -p .feynmap/r1/swebench/runs/predictions/deterministic_context.jsonl \
  --run-id feynmap-r1-deterministic \
  -j 1

swebench eval verified \
  -p .feynmap/r1/swebench/runs/predictions/relevance_context.jsonl \
  --run-id feynmap-r1-relevance \
  -j 1

swebench eval verified \
  -p .feynmap/r1/swebench/runs/predictions/dual_channel.jsonl \
  --run-id feynmap-r1-dual \
  -j 1
~~~

Because SWE-bench stores reports beneath each model/run directory, aggregation
can be run after the four evaluation result trees are assembled under a common
report root. The R1 report compares:

- official SWE-bench resolved rate and patch-apply rate;
- first-edit reference-file hit rate;
- reference changed-file recall and precision proxies;
- repository searches and extra-context requests;
- unsupported-claim count;
- elapsed time; and
- model input/output usage.

After the four official evaluations finish, aggregate the complete generation
record tree against the four SWE-bench run directories:

~~~bash
python -m feynmap.judgment.swebench_r1 aggregate \
  experiments/swebench_r1_holdout.json \
  --records-root .feynmap/r1/swebench/runs/records \
  --run-root unassisted=logs/evaluation/feynmap-r1-unassisted \
  --run-root deterministic_context=logs/evaluation/feynmap-r1-deterministic \
  --run-root relevance_context=logs/evaluation/feynmap-r1-relevance \
  --run-root dual_channel=logs/evaluation/feynmap-r1-dual \
  --output .feynmap/r1/swebench/final-report.json \
  --pretty
~~~

Assisted-arm deltas are always reported relative to the unassisted arm. Do not
change retrieval, relevance, role, task-selection or corpus policy after the
holdout is frozen; a policy change requires a new corpus id.

## Remaining work before R1 testing opens

The contracts, dry-run fixtures, and isolated command execution adapter are now
available. Controlled R1 AI testing still requires:

1. a sealed set of new `held_out` tasks;
2. selection/configuration of the first real AI command adapter; and
3. explicit agent/tool versions in every execution environment.

No execution adapter should broaden FeynMap's own read-only authority. The
adapter owns the disposable workspace and process boundary; FeynMap continues to
produce grounding data only.
