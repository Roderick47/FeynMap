# S6.8 — Measured acceptance of the reusable native region router

## Decision

**Route-only native accelerator: ACCEPTED FOR OPTIONAL INTEGRATION (S6.9).**

This is not a production rollout and not a claim that full FeynMap is 20x
faster. Normal RegionIndex.route() still runs Python. S6.9 must measure the
representative full adaptive/minimal workflow once optional routing is wired
in before considering a production-default decision.

## Method

feynmap/rust_routing_performance.py measures the full observable native route:

Python anchor lookup and query tokenization -> compact numeric request ->
Python/PyO3 argument conversion -> compiled Rust routing and scoring ->
numeric response conversion -> normal FeynMap RegionRouteResult.

The reference timing calls the original Python RegionIndex.route() with the
same six FeynMap self-hosting queries, same anchor-node IDs, same region budget
and the same already-built RegionIndex. Both paths are executed on the SAME
runner, after warm-up. Five paired 1,200-call measurement samples alternate
whether Python or Rust is measured first, and use the median full-block time.

Repository analysis and the common Python RegionIndex construction are
excluded from both repeated-route timing series. Rust's *additional* compact
index preparation and native object construction are explicitly measured
and charged separately through the break-even calculation.

The benchmark also reports a native-kernel-only diagnostic, with Python query
preparation excluded. That number does NOT control acceptance: only the full
Python -> Rust -> Python route does.

## First paired CI acceptance result

Workflow: rust-native-build, run 36391589622, functional head bd450887.

| Metric | Python 3.8.18 runner | Python 3.12.14 runner |
|---|---:|---:|
| Original Python route | 1,636.03 us/call | 1,493.48 us/call |
| Full native route | 75.19 us/call | 63.05 us/call |
| Measured native speedup | **21.76x** | **23.69x** |
| Extra one-time native setup | 11.00 ms | 10.13 ms |
| Extra setup break-even | **8 route calls** | **8 route calls** |
| Predeclared end-to-end >= 2.0x gate | PASS | PASS |

These are single-workflow, paired-run medians across five samples on GitHub
Linux x86-64 hosted runners. They are not guaranteed performance figures for
other processors, platforms, repositories or workload distributions.

Why an 8-call break-even matters: native scoring is faster after its numeric
index has been constructed, but building that additional index is not free.
For an index used for only one or two routes, normal Python may still produce
a better *total* latency. A long-lived index servicing multiple agent queries
is the kind of reuse pattern that can realize the measured native benefit.

## Explicit acceptance decision

Minimum criterion selected in S6.4.3: median complete route throughput
improvement of at least 2.0x, preserving exact selected region ordering and
scoring equivalence. Both Python 3.8 and Python 3.12 pass independently.

Correctness precondition: S6.7 passes 126 three-way cases per Python version:
12 independently expected oracle cases, 108 deterministic stress requests
and six real recursive FeynMap queries. Normal Python regression and recursive
self-analysis workflows remain green. Both result files are retained as
separate GitHub Actions artifacts.

The performance job fails CI if either interpreter misses the 2.0x gate, if
the quality-equivalence condition fails, or if the paired benchmark workload
does not match the pinned 1,200 calls per sample.

## Net effect on broader FeynMap

Zero production impact so far: normal FeynMap still invokes the Python router.
The native result is a controlled shadow benchmark, not an end-to-end active
agent benchmark. Consequently, neither a full sparse-search latency speedup
nor a full minimal-context cost reduction has been established yet.

S6.9 must keep the native path optional, implement fallback, and benchmark
whole representative self-hosted workflows *with it actually selected*.
Native index lifecycle and amortized setup are first-class requirements;
turning Rust on unconditionally for a single-route one-shot session may
erase the gain demonstrated by this S6.8 routing-only test.

## Assets

- feynmap/rust_routing_performance.py: paired five-sample test and break-even report.
- tests/test_rust_routing_performance.py: threshold/math unit tests without Rust.
- .github/workflows/rust-native-build.yml: Python 3.8 and 3.12 paired reports
  plus final cross-interpreter acceptance gate.
- GitHub Actions artifacts: s6-8-routing-performance-py38 and
  s6-8-routing-performance-py312 (same workflow run).

## Rust lesson: speedup and amortization

Rust has removed much of Python's repeated interpreter overhead from the
token-scoring loop, but conversion and setup remain real costs. 'Amortization'
means paying a one-time cost once and spreading it over many uses. The
break-even calculation is:

    ceil(extra_native_setup_time / (python_route_time - native_route_time))

when the native path saves time on each route. This is why a fast Rust kernel
does not automatically justify enabling it for every FeynMap request.

S6.8 is complete. S6.9 may begin optional integration on this same short-lived
feature/rust-routing-kernel branch, subject to full-workflow evidence.
