# P2.1 — Source-role-aware minimal context (opt-in)

**Scope:** Fix a delivery-policy defect exposed by P1 without changing the
static semantic graph, source facts, evidence tiers, default S3 behavior,
frozen P1.1 development manifest or P1.7 baseline score. Full P2 is staged in
`docs/P2_DELIVERY_EXECUTION.md`.

## Observed failure

In the pinned DRF source at revision
`b578eab1cad040414b758131af1e17aa000b51e2`, P1.6 recovered an exact,
source-backed relation from
`SerializerMetaclass._get_declared_fields` to the imported
`rest_framework.fields.Field`. Both `serializers.py` and `fields.py`
became *activated*. The legacy packer, however, delivered 13 semantic nodes
under 3,197 context tokens: 11 test nodes and 2 other nodes, including
`serializers.py` but not `fields.py`.

P2.1 compares **the exact same S2 activated GuidedSearchResult** through
two independent S3 policies. Neither policy receives a benchmark gold
`essential_files` list when selecting nodes. The frozen P1 probe remains
scored using the legacy default.

## Policy

Source paths are classified as implementation, test, migration,
vendor/generated, documentation or configuration. A name that happens to
contain `test` in an implementation symbol does not change its channel.
An explicit test/migration/vendor request may prefer that channel; ordinary
implementation questions first reserve up to two distinct activated source
files, ranked by query relevance and actual grounded cross-file behavioral
edges. A non-test request limits optional test selection to 35% of
`max_nodes`, not 35% of tokens. Test questions are exempt from that cap
and retain implementation context as support.

Every selected node must already be in the search's activated result. Every
selected edge must be one of the existing activated edges and retain *both*
actual endpoints. An implementation source witness may become an additional
explicit anchor if retaining its entire test-heavy search-parent path would
overspend the budget; no missing ancestor edge or runtime fact is invented.
The fixed source graph, evidence and output payload schema are unchanged.

**Opt-in API:**

```python
from feynmap import DeliveryChannelPolicy, SparseContextPipeline
from feynmap.minimal_context import MinimalContextBudget

result = SparseContextPipeline(graph).concept(
    "How are serializer fields and validation resolved?",
    context_budget=MinimalContextBudget(
        max_tokens=3200, max_nodes=24, max_edges=24,
    ),
    delivery_policy=DeliveryChannelPolicy(
        mode="implementation_first",
        min_implementation_files=2,
        max_test_fraction=0.35,
    ),
)
```

Omitting `delivery_policy` retains bit-for-bit legacy selection behavior.
The P1 probe runner records source-first results additively in
`p2_role_aware_shadow` and gates actual source provenance, endpoint
integrity, token/node/edge caps, per-channel counts and delivery of both
original source-authored DRF retrieval expectations.

## First independently pinned acceptance (29 September 2026)

Run: [p1-external-semantic-baseline 36539921382](https://github.com/Roderick47/FeynMap/actions/runs/36539921382).
The same-activation P2.1 source-first shadow passes **both DRF retrieval
questions** while the unchanged P1 delivery score remains **10/11**.

| Pinned question | Legacy delivered nodes | Legacy tokens | Source-first delivered nodes | Source-first tokens | Source-first essential implementation files |
|---|---:|---:|---:|---:|---|
| Throttling implementation | 11 (1 test) | 1,944 | 4 (0 tests) | 809 | All delivered |
| Serializer fields and validation | 13 (11 tests) | 3,197 | 5 (2 tests) | 1,219 | Both `serializers.py` and `fields.py` delivered |

The serializer shadow carries three implementation nodes and two test nodes,
including actual test evidence from `tests/test_filters.py` and
`tests/test_validation.py`. Its source relation survived and no item was
added from outside activation. These are **semantic context-node and file
coverage** measurements, not literal source-code byte recall, test token
share, answer correctness, hallucination rate or user-task success.

The controlled shadow changes only selection, not upstream search. Its token
figures are one-run outputs and should not be interpreted as performance
distributions. The original 11 source expectations, real P1.7 acceptance,
Python 3.8/3.12 contract and negative fixtures, and recursive self-check
remain separate regression controls.

## Remaining P2 work

P2.2 must test an independently authored migration/control question, test-
specific retrieval, symbol-level implementation recall and genuine necessary
test evidence. It must quantify distractor tokens instead of inferring their
share from node counts; compare all budgets fairly under identical activation.
P2.3 can then assess real downstream answer fidelity before selecting a
default policy. A known development query and synthetic source fixtures are
not the sealed, disjoint S7 held-out agent-repair evaluation.
