from dataclasses import dataclass

import pytest

from feynmap.grounding import GROUNDING_TOOL_CONTRACT_VERSION, GROUNDING_TOOLS
from feynmap.tool_space import (
    TOOL_CAPABILITY_SCHEMA,
    TOOL_SELECTION_SCHEMA,
    DeterministicToolSelector,
    ToolCapabilityNode,
    ToolCapabilitySpace,
)


def _grounding_space():
    return ToolCapabilitySpace.from_contracts(
        GROUNDING_TOOLS,
        namespace="grounding",
        contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
    )


def test_every_grounding_tool_becomes_one_stable_capability_node():
    space = _grounding_space()

    assert len(space.nodes) == len(GROUNDING_TOOLS)
    assert {node.name for node in space.nodes} == {
        tool.name for tool in GROUNDING_TOOLS
    }
    assert all(node.id.startswith("tool:grounding:") for node in space.nodes)
    assert all(node.contract_digest for node in space.nodes)


def test_capability_node_is_grounded_in_declared_tool_contract():
    space = _grounding_space()
    tool = next(item for item in GROUNDING_TOOLS if item.name == "trace_path")
    node = space.node("trace_path")

    assert node is not None
    assert node.description == tool.description
    assert node.input_schema == tool.input_schema
    assert node.read_only is tool.read_only
    assert node.contract_version == GROUNDING_TOOL_CONTRACT_VERSION
    assert node.required_inputs == ("source", "target")
    assert set(node.optional_inputs) == {"direction", "max_depth"}
    assert {"trace", "path", "source", "target", "incoming", "outgoing"} <= set(node.terms)


def test_capability_digest_is_independent_of_schema_dictionary_order():
    @dataclass(frozen=True)
    class Contract:
        name: str
        description: str
        input_schema: dict
        read_only: bool = True

    first = Contract(
        "lookup",
        "Lookup a symbol.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "depth": {"type": "integer"},
            },
            "required": ["symbol"],
        },
    )
    second = Contract(
        "lookup",
        "Lookup a symbol.",
        {
            "required": ["symbol"],
            "properties": {
                "depth": {"type": "integer"},
                "symbol": {"type": "string"},
            },
            "type": "object",
        },
    )

    left = ToolCapabilityNode.from_contract(
        first,
        namespace="test",
        contract_version="1",
    )
    right = ToolCapabilityNode.from_contract(
        second,
        namespace="test",
        contract_version="1",
    )

    assert left.contract_digest == right.contract_digest
    assert left.id == right.id
    assert left.required_inputs == right.required_inputs
    assert left.optional_inputs == right.optional_inputs


def test_tool_space_serialization_is_deterministic_and_contains_no_selection_result():
    first = _grounding_space()
    second = ToolCapabilitySpace.from_contracts(
        tuple(reversed(GROUNDING_TOOLS)),
        namespace="grounding",
        contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
    )

    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert all(node["schema"] == TOOL_CAPABILITY_SCHEMA for node in payload["nodes"])
    assert "selected" not in payload
    assert "scores" not in payload


def test_duplicate_tool_names_are_rejected():
    tool = GROUNDING_TOOLS[0]

    with pytest.raises(ValueError, match="duplicate tool capability ids"):
        ToolCapabilitySpace.from_contracts(
            (tool, tool),
            namespace="grounding",
            contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
        )



def test_deterministic_selector_ranks_find_callers_for_incoming_call_query():
    selector = DeterministicToolSelector(_grounding_space())

    result = selector.select(
        "Find incoming callers and invocations for this symbol",
        limit=3,
    )

    assert result.hits
    assert result.hits[0].node.name == "find_callers"
    assert {"incoming", "callers"} <= set(result.hits[0].matched_terms)
    assert len(result.hits) <= 3


def test_deterministic_selector_ranks_semantic_diff_for_snapshot_comparison():
    selector = DeterministicToolSelector(_grounding_space())

    result = selector.select(
        "Compare semantic graph changes between two immutable snapshots",
        limit=2,
    )

    assert result.hits
    assert result.hits[0].node.name == "semantic_diff"


def test_deterministic_selector_is_stable_across_capability_input_order():
    forward = DeterministicToolSelector(_grounding_space())
    reverse_space = ToolCapabilitySpace.from_contracts(
        tuple(reversed(GROUNDING_TOOLS)),
        namespace="grounding",
        contract_version=GROUNDING_TOOL_CONTRACT_VERSION,
    )
    reverse = DeterministicToolSelector(reverse_space)

    left = forward.select("trace path between source and target symbols", limit=4)
    right = reverse.select("trace path between source and target symbols", limit=4)

    assert left.to_dict() == right.to_dict()
    assert left.hits[0].node.name == "trace_path"


def test_deterministic_selector_returns_no_guess_for_unmatched_query():
    selector = DeterministicToolSelector(_grounding_space())

    result = selector.select("quantum banana orchestra", limit=4)

    assert result.hits == ()
    assert result.actionable_query_terms == ()


def test_deterministic_selector_respects_limit_and_serializes_without_full_schemas():
    selector = DeterministicToolSelector(_grounding_space())

    result = selector.select("symbol evidence relationships graph", limit=2)
    payload = result.to_dict()

    assert payload["schema"] == TOOL_SELECTION_SCHEMA
    assert payload["selected_count"] <= 2
    assert 0.0 <= payload["selection_ratio"] <= 1.0
    assert all("input_schema" not in hit for hit in payload["hits"])


def test_deterministic_selector_requires_non_empty_query():
    selector = DeterministicToolSelector(_grounding_space())

    with pytest.raises(ValueError, match="query is required"):
        selector.select("   ")
