# S6.1: Python hot-path profile

S6.1 adds a reproducible `cProfile` harness for the two established sparse
substrate workloads: adaptive activation plus minimal-context packing, and
tool routing plus schema delivery. It records total and primitive calls, top
cumulative functions, top self-time functions, and FeynMap-module self time.

The checked-in workload runs one self-hosting activation benchmark pass and 25
tool-routing benchmark iterations. It intentionally does not profile live JEV
or network work. Profiled elapsed time includes `cProfile` overhead and is
useful for comparing the same harness across revisions, not as a production
latency promise.

The analyzed repository root and FeynMap's installed source root are tracked
independently. FeynMap hotspot tables therefore remain populated when the
profile target is another repository. Workloads default to one iteration when
the field is omitted.

## Local baseline

On the initial Python 3.12 local run:

| Workload | Profiled elapsed | Main cumulative costs | Main FeynMap self-time cost |
|---|---:|---|---|
| Adaptive activation + minimal context | 13.80 s | analysis 8.69 s; minimal packing 3.72 s | framework Python node lookup, 0.99 s |
| Tool routing + schema delivery, 25 runs | 1.12 s | selector 0.45 s; tokenization 0.43 s | `tool_space.py`, 0.40 s |

This establishes the S6.1 decision record: profile evidence points first to
analysis and minimal-context packing for end-to-end latency, and to routing
tokenization/scoring for repeated tool-space calls. S6.2 must measure a
candidate cache against these workloads before changing the hot path.

Run it locally with:

```text
python -m feynmap.performance_profile experiments/performance_profile_s6.json . --output performance-results/s6-1.json
```
