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

## Remaining work before R1 testing opens

The contracts, dry-run fixtures, and isolated command execution adapter are now
available. Controlled R1 AI testing still requires:

1. deterministic context generation for the three assisted arms;
2. a sealed set of new `held_out` tasks;
3. selection/configuration of the first real AI command adapter; and
4. explicit agent/tool versions in every execution environment.

No execution adapter should broaden FeynMap's own read-only authority. The
adapter owns the disposable workspace and process boundary; FeynMap continues to
produce grounding data only.
