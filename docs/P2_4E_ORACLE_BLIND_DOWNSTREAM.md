# P2.4e — Oracle-isolated downstream answer runner

P2.4e prepares the first **oracle-blind downstream model run** over the already-frozen P2.4d packets. It does not alter P2.4c retrieval, P2.4d source, the frozen P2.4d oracle, or any P2.4d model packet.

## Why this exists

P2.4d established two distinct results:

- fresh behavioral evidence availability: repaired P2.4c retained **16/17** preregistered behavioral patterns;
- oracle-exposed downstream diagnostic: repaired P2.4c supported **19/20** grounded claims and **6/7** answerable tasks.

The second result cannot promote a default because that interactive answer run occurred in a session that had already seen the source/oracle. P2.4e therefore isolates the downstream answer process from every gold/scorer input.

## Isolation boundary

`feynmap/p2_4e_blind_answer.py` intentionally imports no FeynMap modules. Its only semantic input is a directory of `feynmap.p2_4d_model_input.v1` JSON packets.

The GitHub workflow re-exports the frozen P2.4d packets on the host, then starts a clean `python:3.12-slim` container with only:

1. `/inputs` — read-only P2.4d `model_inputs/*.json` packets;
2. `/runner.py` — the standalone blind-answer runner;
3. `/answers` — an empty writable output directory;
4. the provider credential as an environment variable.

The rollout source fixture, frozen manifest/oracle, scorer index, repository checkout, and previous answer files are **not mounted into the model container**.

The scorer runs only after the provider process exits, outside the isolated model process.

## Provider contract

The first supported protocol is the OpenAI Responses API. The runner defaults to `gpt-6-luna` unless `FEYNMAP_BLIND_MODEL` is explicitly set. `FEYNMAP_OPENAI_BASE_URL` may override the default API base URL through the workflow variable `FEYNMAP_OPENAI_BASE_URL`.

The model receives one packet per request and must emit strict structured JSON:

```json
{
  "status": "answer | need_more_context",
  "claims": [
    {
      "text": "source-grounded atomic claim",
      "evidence_refs": ["ref present in the packet"]
    }
  ],
  "missing_identifiers": []
}
```

The runner rejects any citation that is not present in the packet before the answer can reach the P2.4d scorer. Provider tools are not enabled and provider-side storage is requested as `false`.

## Credential boundary

The workflow deliberately requires a repository secret named:

`FEYNMAP_OPENAI_API_KEY`

It does not fall back to a generic secret, a mock provider, this ChatGPT session, or a deterministic answer generator. This prevents an accidental nonblind or non-model run from being labeled oracle-blind evidence.

On the first P2.4e workflow run (`37387181641`) the runner contract passed, but the explicit provider secret was not configured. The provider and scoring steps were therefore skipped and the uploaded status was:

`not_run_missing_explicit_provider_credential`

No oracle-blind downstream result is claimed from that run.

## Regression status

At runner commit `a1c50b51246d9cc8c6c7e85a06315d498f457514`:

- runner contract tests: pass;
- Python 3.8 full suite: pass;
- Python 3.12 full suite: pass;
- recursive self-analysis: pass.

The machine-readable checkpoint is `experiments/results/p2_4e_20261006_oracle_blind_status.json`.

## Next valid evaluation

The next valid evidence requires no code or corpus changes:

1. configure `FEYNMAP_OPENAI_API_KEY` intentionally;
2. run `.github/workflows/p2-4e-oracle-blind.yml`;
3. preserve the resulting provider/model identity and actual token usage;
4. score those answers using the unchanged P2.4d scorer;
5. report the comparative and absolute fidelity gates exactly as produced.

If the blind run fails a preregistered task, that failure must be recorded. P2.4c and the P2.4d corpus must not be tuned against it and rescored as if still fresh.

P2.4e does not use S7, does not change the legacy product default, and does not establish learned-relevance superiority.
