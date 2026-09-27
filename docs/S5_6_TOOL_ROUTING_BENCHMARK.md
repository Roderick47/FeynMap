# S5.6: tool-routing and schema-delivery benchmark

S5.6 adds a deterministic, provider-free benchmark over all 13 grounding tool
contracts. Its checked-in dataset contains 14 positive tasks (one for each
clear contract route plus one deliberately ambiguous evidence query) and one
unmatched negative task.

The benchmark separates three questions:

1. Did deterministic ranking place a labeled tool first?
2. Did the sufficiency policy actually deliver the labeled schema?
3. How many estimated model-facing tool-contract tokens were avoided compared
   with sending the full catalog on every task?

The token metric uses FeynMap's existing deterministic estimate: the ceiling
of canonical JSON characters divided by four. It measures the complete
delivered tool-definition payload (identity, description, input schema,
read-only flag, version, and digest), not a vendor tokenizer's exact billing.

## Local baseline

The accepted local Python 3.12 run over `experiments/tool_routing_s5.json`
produced:

| Metric | Result |
|---|---:|
| Positive top-1 accuracy | 100% (14/14) |
| Mean reciprocal rank | 1.000 |
| Positive delivery recall | 92.9% (13/14) |
| Unmatched-query accuracy | 100% (1/1) |
| Overall task success | 93.3% (14/15) |
| Full-catalog payload | 2,054 estimated tokens/task |
| Full-catalog aggregate | 30,810 estimated tokens |
| Delivered aggregate | 7,874 estimated tokens |
| Tokens avoided | 22,936 estimated tokens |
| Schema-token reduction | 74.4% |
| Mean delivered tools | 3.33 of 13 |

The one positive delivery miss is intentional: `Show symbol evidence
relationships graph` ranks `explain_evidence` first but fails the deterministic
margin check, so a no-provider run delivers no schema. This records the S5.4
escalation boundary instead of treating an ambiguous lexical lead as certain.

These are contract-routing results on an internally labeled seed set. They do
not establish downstream answer quality, tool-execution correctness, natural
language generalization, or live JEV quality. The workflow uploads the complete
JSON result so later runs can be compared without changing these claims.
