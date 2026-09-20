# Adversarial fixture review record

Base revision: merged PR #25 (`646fff2`). Expectations were written from fixture
source before running the analyzer. They were not generated from its output.

**Review status:** authored and reviewed during implementation; Python and Node
execution witnesses passed. A separate human or independently assigned reviewer
has not reviewed these labels. Do not describe this as an independently reviewed
corpus. The tables and witnesses below provide a concrete review package.

## Scope of judgments

These labels test **justified static target resolution**. A negative callback or
member-call label means the source does not justify binding that call to the
same-named module function. It does not claim that the target is impossible under
all arguments. Passing the module helper explicitly as a callback could invoke
it. Runtime witnesses below use the stated concrete inputs only.

## Source rationale, written before analysis

| Case | Source → target | Expected resolved relationship | Reason |
| --- | --- | --- | --- |
| Python | actual → package helper | calls | Unshadowed imported alias resolves through package re-export. |
| Python | parameter → package helper | absent | `helper` is a parameter, not the imported binding. Witness passes a distinct lambda. |
| Python | local → package helper | absent | Local lambda assignment shadows the imported binding. |
| JavaScript | actual → global helper | calls | Bare call refers to the top-level function. |
| JavaScript | member → global helper | absent | `obj.helper()` is a member lookup; spelling alone cannot establish the global target. Witness supplies a different member. |
| JavaScript | commentOnly → global helper | absent | Comment text is not executable code. |
| JavaScript | stringOnly → global helper | absent | Returned string contents are not executed. |
| JavaScript | outer → global helper | absent | Declaring inner does not execute inner's body; outer never calls it. |
| JavaScript | inner → global helper | calls | Inner's body contains a bare call to the global helper. This is a body-level relation, not a claim that inner runs. |
| HTTP | readItems → get_items | requests | This fetch has no options and defaults to GET. |
| HTTP | readItems → post_items | absent | The next function's POST options cannot apply to this call. |
| HTTP | writeItems → post_items | requests | This call explicitly sets POST. |
| HTTP | writeItems → get_items | absent | Explicit POST does not match the GET-only route. |

## Before/after results

These are labeled fixture counts, not whole-repository accuracy estimates.

| Fixture | Before TP / FP / FN / TN | After TP / FP / FN / TN |
| --- | --- | --- |
| Python scope | 1 / 2 / 0 / 0 | 1 / 0 / 0 / 2 |
| JavaScript scope | 2 / 4 / 0 / 0 | 2 / 0 / 0 / 4 |
| HTTP methods | 1 / 1 / 1 / 1 | 2 / 0 / 0 / 2 |

All 13 labels now pass. Seven false bindings and one missed relationship were
exposed by the baseline fixtures.

## Independent execution mechanisms, not independent reviewers

`tests/test_adversarial_fixtures.py` includes:

- A Python subprocess with `sys.setprofile`, counting actual calls to the package
  helper. Only `actual()` reaches it for the specified inputs.
- A Node VM executing the JavaScript source with an instrumented helper and an
  object with a distinct helper method. Only `actual()` invokes the global helper
  in the tested workload; inner is not executed by outer.
- A separate Node VM recording fetch arguments through a stub. It records GET,
  then POST. No network is used and Flask is not executed by these witnesses.

The Python witness uses the running interpreter. The Node witness is skipped
when Node is absent; it passed, without skipping, in the implementation environment.

## How to review

Read each source file and challenge the rationale above before looking at FeynMap
output. Run `python -m pytest tests/test_adversarial_fixtures.py`. In particular,
verify that negative labels mean unsupported static binding under this contract,
not global impossibility. Add counterexamples as new labels/fixtures, rather than
relaxing a failing expected result to match analyzer output.
