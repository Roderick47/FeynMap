import copy
import json
from pathlib import Path

import pytest

from feynmap.active_state import ActiveState, ActiveStateInvalidated, ActiveStateRuntime
from feynmap.core import SemanticGraph
from feynmap.grounding import GroundingTool
from feynmap.snapshots import (
    RepositorySnapshot,
    _canonical_json,
    _graph_identity_hash,
    _sha256_text,
)
from feynmap.tool_delivery import DeliveredToolSchema, ToolSchemaPack
from feynmap.tool_space import ToolCapabilityNode, ToolCapabilitySpace


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "contracts"
    / "s6_contracts_v1.json"
)


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_semantic_graph_conformance_fixture_roundtrips_exactly():
    payload = _fixture()["semantic_graph"]

    restored = SemanticGraph.from_dict(payload)

    assert restored.to_dict() == payload


def test_semantic_graph_rejects_unsupported_major_and_unknown_semantic_enum():
    payload = copy.deepcopy(_fixture()["semantic_graph"])
    payload["schema_version"] = "2.0.0"

    with pytest.raises(ValueError, match="schema version"):
        SemanticGraph.from_dict(payload)

    payload = copy.deepcopy(_fixture()["semantic_graph"])
    payload["nodes"][0]["kind"] = "future_semantic_kind"

    with pytest.raises(ValueError):
        SemanticGraph.from_dict(payload)


def test_semantic_graph_can_read_additive_optional_top_level_field_without_semantic_change():
    canonical = _fixture()["semantic_graph"]
    payload = copy.deepcopy(canonical)
    payload["future_optional"] = {
        "note": "read-only consumers may ignore additive optional fields"
    }

    restored = SemanticGraph.from_dict(payload)

    assert restored.to_dict() == canonical


def test_semantic_graph_identity_vector_is_fixed_and_order_independent():
    fixture = _fixture()
    payload = fixture["semantic_graph"]
    expected = fixture["identity_vectors"]["semantic_graph_hash"]

    assert _graph_identity_hash(payload) == expected

    reordered = copy.deepcopy(payload)
    reordered["nodes"] = list(reversed(reordered["nodes"]))
    reordered["edges"] = list(reversed(reordered["edges"]))
    assert _graph_identity_hash(reordered) == expected


def test_repository_snapshot_fixture_and_identity_vectors_are_deterministic():
    fixture = _fixture()
    payload = fixture["repository_snapshot"]
    vectors = fixture["identity_vectors"]

    restored = RepositorySnapshot.from_dict(payload)

    assert restored.to_dict() == payload
    assert _sha256_text(payload["locator"]) == vectors["repository_key"]
    assert _sha256_text(
        _canonical_json(payload["files"])
    ) == vectors["content_hash"]
    assert _sha256_text(
        _canonical_json(vectors["snapshot_identity_payload"])
    ) == vectors["snapshot_id"]
    assert payload["graph_hash"] == vectors["semantic_graph_hash"]


def test_repository_snapshot_rejects_unsupported_nested_graph_major():
    payload = copy.deepcopy(_fixture()["repository_snapshot"])
    payload["graph_schema_version"] = "2.0.0"

    with pytest.raises(ValueError, match="graph schema version"):
        RepositorySnapshot.from_dict(payload)


def test_active_state_fixture_roundtrips_and_remains_snapshot_bound():
    fixture = _fixture()
    graph = SemanticGraph.from_dict(fixture["semantic_graph"])
    state = ActiveState.from_dict(fixture["active_state"])

    assert state.to_dict() == fixture["active_state"]

    runtime = ActiveStateRuntime(graph, state.snapshot_id)
    hydrated = runtime.rehydrate(state)
    assert hydrated["snapshot_id"] == state.snapshot_id
    assert {node["id"] for node in hydrated["nodes"]} == set(
        state.active_node_ids
    )

    changed_runtime = ActiveStateRuntime(graph, "different-snapshot")
    with pytest.raises(ActiveStateInvalidated, match="snapshot changed"):
        changed_runtime.rehydrate(state)


def test_tool_capability_and_space_match_fixed_digest_fixture():
    fixture = _fixture()
    expected = fixture["tool_capability"]
    tool = GroundingTool(
        name=expected["name"],
        description=expected["description"],
        input_schema=expected["input_schema"],
        read_only=expected["read_only"],
    )

    node = ToolCapabilityNode.from_contract(
        tool,
        namespace=expected["namespace"],
        contract_version=expected["contract_version"],
    )
    space = ToolCapabilitySpace.from_contracts(
        [tool],
        namespace=expected["namespace"],
        contract_version=expected["contract_version"],
    )

    assert node.contract_digest == fixture["identity_vectors"]["tool_contract_digest"]
    assert node.to_dict() == expected
    assert space.to_dict() == fixture["tool_capability_space"]


def test_tool_contract_digest_is_independent_of_schema_object_key_order():
    fixture = _fixture()
    expected = fixture["tool_capability"]
    schema = expected["input_schema"]
    reordered_schema = {
        key: schema[key]
        for key in reversed(list(schema))
    }
    tool = GroundingTool(
        expected["name"],
        expected["description"],
        reordered_schema,
        expected["read_only"],
    )

    node = ToolCapabilityNode.from_contract(
        tool,
        namespace=expected["namespace"],
        contract_version=expected["contract_version"],
    )

    assert node.contract_digest == fixture["identity_vectors"]["tool_contract_digest"]


def test_tool_schema_pack_matches_model_facing_conformance_fixture():
    fixture = _fixture()
    expected = fixture["tool_capability"]
    tool = GroundingTool(
        expected["name"],
        expected["description"],
        expected["input_schema"],
        expected["read_only"],
    )
    node = ToolCapabilityNode.from_contract(
        tool,
        namespace=expected["namespace"],
        contract_version=expected["contract_version"],
    )
    delivered = DeliveredToolSchema.from_node(node)
    pack = ToolSchemaPack(
        query="find callers for symbol",
        route_sufficient=True,
        route_reason="conformance_fixture",
        available_tool_count=1,
        selected_tool_count=1,
        tools=(delivered,),
    )

    assert pack.to_dict() == fixture["tool_schema_pack"]
