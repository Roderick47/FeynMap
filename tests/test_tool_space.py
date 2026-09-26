from dataclasses import dataclass

import pytest

from feynmap.grounding import GROUNDING_TOOL_CONTRACT_VERSION, GROUNDING_TOOLS
from feynmap.tool_space import (
    TOOL_CAPABILITY_SCHEMA,
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
