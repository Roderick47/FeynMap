# S5.4: ambiguity-aware tool routing

`AdaptiveToolRouter` in `feynmap.tool_routing` wraps the S5.3 selector. It
accepts a `ToolCapabilitySpace` and an optional existing `JudgmentProvider`
(including `JevJudgmentProvider`); no provider is created automatically.

```python
router = AdaptiveToolRouter(space, provider=provider)
result = router.route("Find incoming callers for this symbol", limit=4)
```

The deterministic path is sufficient when the top lexical score is at least
0.5 and leads the runner-up by at least 0.15. These configurable thresholds
are heuristics, not probabilities or guarantees of task completion. The
runner-up is checked even for `limit=1`. Unmatched queries return no tools and
never invoke a provider.

Otherwise the provider receives at most `candidate_limit` grounded candidates
(default 4, minimum 2), containing IDs, names, descriptions, lexical scores,
and matched terms. A bounded choice question permits one of those IDs or
abstention. The router validates the returned answer type and exact candidate
membership independently of the provider. A valid choice returns one original
candidate; abstention returns none. Original lexical scores retain their meaning.

Without a provider, the deterministic selection is retained and marked
insufficient. Invalid/missing answers and `JudgmentProviderError` likewise
retain that baseline with an explicit reason. Other unexpected programming
errors propagate. Callers can inspect `sufficient`, `reason`, and
`provider_called`; no canonical graph state is changed.

This checkpoint adds no tool execution, schema packing, or S5.5 behavior.
