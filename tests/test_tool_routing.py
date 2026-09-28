from dataclasses import dataclass

import pytest

from feynmap.grounding import GROUNDING_TOOLS, GROUNDING_TOOL_CONTRACT_VERSION
from feynmap.judgment.contracts import (
    JudgmentAnswer, JudgmentKind, JudgmentProvider, JudgmentProviderError, JudgmentResult,
)
from feynmap.tool_space import ToolCapabilitySpace, DeterministicToolSelector
from feynmap.tool_routing import AdaptiveToolRouter


def space(tools=GROUNDING_TOOLS):
    return ToolCapabilitySpace.from_contracts(
        tools, namespace="grounding", contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
    )


class Provider(JudgmentProvider):
    name = "fake"

    def __init__(self, value=None, kind=JudgmentKind.CHOICE, fail=False):
        self.value, self.kind, self.fail = value, kind, fail
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        if self.fail:
            raise JudgmentProviderError("unavailable")
        value = self.value or state["candidates"][1]["tool_id"]
        return JudgmentResult(self.name, None, {
            "tool_choice": JudgmentAnswer(self.kind, value),
        })


@pytest.mark.parametrize("query,expected", [
    ("Find incoming callers and invocations for this symbol", "find_callers"),
    ("Compare semantic graph changes between two immutable snapshots", "semantic_diff"),
    ("trace path between source and target symbols", "trace_path"),
])
def test_obvious_queries_stay_cheap(query, expected):
    provider = Provider()
    result = AdaptiveToolRouter(space(), provider=provider).route(query)
    assert result.sufficient
    assert result.selection.hits[0].node.name == expected
    assert not result.provider_called
    assert provider.calls == []


QUERY = "symbol evidence relationships graph"


def test_ambiguous_query_uses_bounded_grounded_judgment_even_with_limit_one():
    provider = Provider()
    result = AdaptiveToolRouter(space(), provider=provider, candidate_limit=2).route(QUERY, limit=1)
    state, questions = provider.calls[0]
    assert len(state["candidates"]) == 2
    ids = {item["tool_id"] for item in state["candidates"]}
    assert set(questions["tool_choice"].criteria) == ids | {"abstain"}
    assert all("input_schema" not in item for item in state["candidates"])
    assert result.selection.hits[0].node.id == state["candidates"][1]["tool_id"]
    assert result.reason == "provider_selected"
    assert result.sufficient and result.provider_called


@pytest.mark.parametrize("value,kind", [
    ("tool:grounding:invented", JudgmentKind.CHOICE),
    ("tool:grounding:trace_path", JudgmentKind.CHOICE),
    ([], JudgmentKind.SCORE),
    (0.9, JudgmentKind.NOUL),
])
def test_provider_cannot_escape_shortlist_or_use_wrong_answer_type(value, kind):
    provider = Provider(value, kind)
    result = AdaptiveToolRouter(space(), provider=provider, candidate_limit=2).route(QUERY)
    baseline = DeterministicToolSelector(space()).select(QUERY)
    assert result.selection == baseline
    assert result.reason == "invalid_provider_answer"
    assert not result.sufficient


@pytest.mark.parametrize("query", ["quantum banana orchestra", "the and of"])
def test_unmatched_queries_never_call_provider(query):
    provider = Provider()
    result = AdaptiveToolRouter(space(), provider=provider).route(query)
    assert result.selection.hits == ()
    assert result.reason == "unmatched"
    assert provider.calls == []


def test_no_provider_is_deterministic_across_contract_order():
    first = AdaptiveToolRouter(space()).route(QUERY, limit=1)
    second = AdaptiveToolRouter(space(tuple(reversed(GROUNDING_TOOLS)))).route(QUERY, limit=1)
    assert first.to_dict() == second.to_dict()
    assert first.selection == DeterministicToolSelector(space()).select(QUERY, limit=1)
    assert not first.sufficient and not first.provider_called
    assert first.reason == "ambiguous_margin"


def test_provider_abstention_returns_no_tools():
    result = AdaptiveToolRouter(space(), provider=Provider("abstain")).route(QUERY)
    assert result.selection.hits == ()
    assert result.reason == "provider_abstained"


def test_provider_error_preserves_deterministic_fallback():
    result = AdaptiveToolRouter(space(), provider=Provider(fail=True)).route(QUERY)
    assert result.selection == DeterministicToolSelector(space()).select(QUERY)
    assert result.reason == "provider_error"
    assert not result.sufficient


@pytest.mark.parametrize("kwargs", [
    {"min_score": float("nan")}, {"min_margin": -1},
    {"min_margin": float("inf")}, {"candidate_limit": 1},
])
def test_policy_validation(kwargs):
    with pytest.raises(ValueError):
        AdaptiveToolRouter(space(), **kwargs)


def test_empty_space_and_blank_query():
    router = AdaptiveToolRouter(space(()), provider=Provider())
    assert router.route("symbol").selection.hits == ()
    with pytest.raises(ValueError):
        router.route(" ")


def test_low_score_requires_judgment_even_without_close_runner_up():
    provider = Provider("abstain")
    router = AdaptiveToolRouter(space(), provider=provider, min_score=0.95)
    result = router.route("trace path between source and target symbols")
    assert result.provider_called
    assert result.reason == "provider_abstained"
    fallback = AdaptiveToolRouter(space(), min_score=0.95).route(
        "trace path between source and target symbols"
    )
    assert fallback.reason == "low_score"
    assert not fallback.sufficient


def test_missing_provider_answer_is_rejected():
    class MissingAnswer(Provider):
        def evaluate(self, state, questions):
            return JudgmentResult(self.name, None, {})

    result = AdaptiveToolRouter(space(), provider=MissingAnswer()).route(QUERY)
    assert result.reason == "invalid_provider_answer"
    assert result.selection == DeterministicToolSelector(space()).select(QUERY)


def test_exact_tie_remains_ambiguous_and_single_match_can_be_sufficient():
    @dataclass
    class Contract:
        name: str
        description: str = "lookup widget"
        input_schema: object = None
        read_only: bool = True

    tools = [Contract("alpha", input_schema={}), Contract("beta", input_schema={})]
    tied = AdaptiveToolRouter(space(tools)).route("lookup widget", limit=1)
    assert tied.reason == "ambiguous_margin"
    single = AdaptiveToolRouter(space(tools[:1])).route("lookup widget")
    assert single.sufficient
