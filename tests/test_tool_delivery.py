from dataclasses import replace

import pytest

from feynmap.grounding import GROUNDING_TOOLS, GROUNDING_TOOL_CONTRACT_VERSION
from feynmap.judgment.contracts import (
    JudgmentAnswer,
    JudgmentKind,
    JudgmentProvider,
    JudgmentResult,
)
from feynmap.tool_delivery import TOOL_SCHEMA_PACK, ToolSchemaPacker
from feynmap.tool_routing import AdaptiveToolRouter
from feynmap.tool_space import ToolCapabilitySpace


def _space(tools=GROUNDING_TOOLS):
    return ToolCapabilitySpace.from_contracts(
        tools,
        namespace="grounding",
        contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
    )


class _SecondCandidateProvider(JudgmentProvider):
    @property
    def name(self):
        return "fake"

    def evaluate(self, state, questions):
        return JudgmentResult(
            provider=self.name,
            model=None,
            answers={
                "tool_choice": JudgmentAnswer(
                    JudgmentKind.CHOICE,
                    state["candidates"][1]["tool_id"],
                )
            },
        )


def test_clear_route_delivers_only_selected_grounded_contracts():
    space = _space()
    routing = AdaptiveToolRouter(space).route(
        "Find incoming callers and invocations for this symbol",
        limit=2,
    )

    packed = ToolSchemaPacker(space, max_tools=2).pack(routing)
    payload = packed.to_dict()

    assert payload["schema"] == TOOL_SCHEMA_PACK
    assert payload["route_sufficient"] is True
    assert payload["selected_tool_count"] == 2
    assert payload["delivered_tool_count"] == 2
    assert [item["tool_id"] for item in payload["tools"]] == [
        hit.node.id for hit in routing.selection.hits
    ]
    assert all("input_schema" in item for item in payload["tools"])
    assert all("score" not in item for item in payload["tools"])
    delivered_ids = {item["tool_id"] for item in payload["tools"]}
    assert delivered_ids < {node.id for node in space.nodes}


def test_provider_choice_delivers_only_the_judged_grounded_schema():
    space = _space()
    routing = AdaptiveToolRouter(
        space,
        provider=_SecondCandidateProvider(),
        candidate_limit=2,
    ).route("symbol evidence relationships graph")

    packed = ToolSchemaPacker(space).pack(routing)

    assert routing.reason == "provider_selected"
    assert len(packed.tools) == 1
    assert packed.tools[0].tool_id == routing.selection.hits[0].node.id


@pytest.mark.parametrize(
    "query,reason",
    [
        ("symbol evidence relationships graph", "ambiguous_margin"),
        ("quantum banana orchestra", "unmatched"),
    ],
)
def test_insufficient_routes_deliver_no_schemas(query, reason):
    space = _space()
    routing = AdaptiveToolRouter(space).route(query)

    packed = ToolSchemaPacker(space).pack(routing)

    assert routing.reason == reason
    assert packed.tools == ()
    assert packed.selected_tool_count == len(routing.selection.hits)
    assert packed.delivery_ratio == 0.0


def test_pack_is_bounded_and_preserves_ranking_order():
    space = _space()
    routing = AdaptiveToolRouter(space).route(
        "Find incoming callers and invocations for this symbol",
        limit=4,
    )

    packed = ToolSchemaPacker(space, max_tools=1).pack(routing)

    assert len(packed.tools) == 1
    assert packed.selected_tool_count == 4
    assert packed.tools[0].tool_id == routing.selection.hits[0].node.id


def test_serialized_schemas_are_defensive_copies():
    space = _space()
    routing = AdaptiveToolRouter(space).route(
        "trace path between source and target symbols",
        limit=1,
    )
    packed = ToolSchemaPacker(space).pack(routing)

    first = packed.to_dict()
    first["tools"][0]["input_schema"]["properties"]["source"]["type"] = "number"
    second = packed.to_dict()

    assert second["tools"][0]["input_schema"]["properties"]["source"]["type"] == "string"
    assert space.node("trace_path").input_schema["properties"]["source"]["type"] == "string"


def test_pack_rejects_tool_from_another_grounded_space():
    space = _space()
    routing = AdaptiveToolRouter(space).route(
        "trace path between source and target symbols",
        limit=1,
    )
    foreign = replace(routing.selection.hits[0].node, contract_digest="foreign")
    forged_hit = replace(routing.selection.hits[0], node=foreign)
    forged_selection = replace(routing.selection, hits=(forged_hit,))
    forged = replace(routing, selection=forged_selection)

    with pytest.raises(ValueError, match="ungrounded"):
        ToolSchemaPacker(space).pack(forged)


def test_pack_rejects_candidate_count_from_another_space():
    space = _space()
    routing = AdaptiveToolRouter(space).route(
        "trace path between source and target symbols",
        limit=1,
    )
    forged = replace(
        routing,
        selection=replace(routing.selection, candidate_count=1),
    )

    with pytest.raises(ValueError, match="different capability space"):
        ToolSchemaPacker(space).pack(forged)


def test_pack_is_stable_across_capability_input_order():
    forward = _space()
    reverse = _space(tuple(reversed(GROUNDING_TOOLS)))
    left = ToolSchemaPacker(forward).pack(
        AdaptiveToolRouter(forward).route("trace path between source and target symbols")
    )
    right = ToolSchemaPacker(reverse).pack(
        AdaptiveToolRouter(reverse).route("trace path between source and target symbols")
    )

    assert left.to_dict() == right.to_dict()


@pytest.mark.parametrize("max_tools", [0, -1, True, 1.5])
def test_pack_limit_must_be_a_positive_integer(max_tools):
    with pytest.raises(ValueError, match="positive integer"):
        ToolSchemaPacker(_space(), max_tools=max_tools)


def test_pack_requires_a_routing_result():
    with pytest.raises(TypeError, match="ToolRoutingResult"):
        ToolSchemaPacker(_space()).pack(object())
