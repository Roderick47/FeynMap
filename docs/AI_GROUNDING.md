# AI Grounding with FeynMap

FeynMap's role is not to make an AI omniscient. Its role is to reduce unnecessary guessing and make uncertainty explicit.

## Grounded workflow

Before editing a symbol, an agent should ask FeynMap for a context bundle containing:

- symbol definition and location,
- outgoing dependencies,
- incoming callers,
- evidence behind each relationship,
- confidence tiers,
- relevant change-impact surfaces.

After proposing an architectural claim, the agent can use claim validation to check whether the graph contains supporting evidence.

## Interpretation rules

- `verified`: strong programmatic evidence.
- `supported`: useful evidence, but review is still appropriate.
- `inferred`: do not treat as fact without additional verification.
- `unknown`: the graph cannot currently support the claim.
- `unsupported`: no matching relationship exists in the current graph. This is not proof of impossibility.

## Desired agent behavior

An AI agent using FeynMap should say:

> FeynMap shows `PaymentView` calls `PaymentService` with static source evidence.

not:

> The repository definitely works this way everywhere.

FeynMap is a grounding layer, not a substitute for compilers, tests, runtime verification, or developer judgment.
