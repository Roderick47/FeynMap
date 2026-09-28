import json
from pathlib import Path

from feynmap.contracts import (
    FROZEN_CONTRACT_SET_SCHEMA,
    FROZEN_CONTRACT_SET_VERSION,
    FROZEN_SUBSTRATE_CONTRACTS,
    PROVISIONAL_SUBSTRATE_SURFACES,
    frozen_contract_manifest,
)
from feynmap.grounding import GroundingTool
from feynmap.tool_space import (
    TOOL_CAPABILITY_SPACE_SCHEMA,
    TOOL_CAPABILITY_SPACE_SCHEMA_VERSION,
    ToolCapabilitySpace,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "contracts"
    / "s6_contracts_v1.json"
)


def _by_key():
    return {contract.key: contract for contract in FROZEN_SUBSTRATE_CONTRACTS}


def test_s6_frozen_contract_set_is_explicit_and_version_pinned():
    contracts = _by_key()

    assert {
        key: contract.version
        for key, contract in contracts.items()
    } == {
        "semantic_graph": "1.0.0",
        "analysis_contract": "1.1.0",
        "confidence_policy": "2.0.0",
        "repository_snapshot": "1.0.0",
        "grounding_tool_catalog": "2.1.0",
        "active_state": "1.0.0",
        "tool_capability": "1.0.0",
        "tool_capability_space": "1.0.0",
        "tool_schema_pack": "1.0.0",
    }


def test_frozen_manifest_keeps_provisional_surfaces_outside_contract_set():
    manifest = frozen_contract_manifest()
    frozen_keys = {item["key"] for item in manifest["contracts"]}

    assert manifest["schema"] == FROZEN_CONTRACT_SET_SCHEMA
    assert manifest["schema_version"] == FROZEN_CONTRACT_SET_VERSION
    assert set(manifest["provisional_surfaces"]) == set(
        PROVISIONAL_SUBSTRATE_SURFACES
    )
    assert not (
        {
            "minimal_context",
            "sparse_context",
            "active_context",
            "judgment_wire_protocol",
            "grounding_result_envelopes",
        }
        & frozen_keys
    )


def test_legacy_graph_family_is_not_relabelled_as_frozen_semantic_graph():
    identifiers = {
        contract.identifier
        for contract in FROZEN_SUBSTRATE_CONTRACTS
        if contract.identifier is not None
    }

    assert "feynmap.semantic_graph" in identifiers
    assert "feynmap.graph" not in identifiers


def test_tool_capability_space_has_independent_frozen_contract_identity():
    tool = GroundingTool(
        "lookup",
        "Look up one grounded symbol.",
        {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    )
    space = ToolCapabilitySpace.from_contracts(
        [tool],
        namespace="grounding",
        contract_version="2.1.0",
    )
    payload = space.to_dict()

    assert payload["schema"] == TOOL_CAPABILITY_SPACE_SCHEMA
    assert payload["schema_version"] == TOOL_CAPABILITY_SPACE_SCHEMA_VERSION
    assert _by_key()["tool_capability_space"].identifier == payload["schema"]
    assert _by_key()["tool_capability_space"].version == payload["schema_version"]


def test_frozen_contract_versions_match_s6_conformance_fixture():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    contracts = _by_key()

    assert fixture["semantic_graph"]["schema_version"] == contracts["semantic_graph"].version
    assert (
        fixture["repository_snapshot"]["schema_version"]
        == contracts["repository_snapshot"].version
    )
    assert fixture["active_state"]["schema_version"] == contracts["active_state"].version
    assert (
        fixture["tool_capability"]["schema_version"]
        == contracts["tool_capability"].version
    )
    assert (
        fixture["tool_capability_space"]["schema_version"]
        == contracts["tool_capability_space"].version
    )
    assert (
        fixture["tool_schema_pack"]["schema_version"]
        == contracts["tool_schema_pack"].version
    )
    assert (
        fixture["tool_capability"]["contract_version"]
        == contracts["grounding_tool_catalog"].version
    )
