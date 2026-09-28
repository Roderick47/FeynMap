"""Frozen cross-runtime substrate contract declaration.

S6.3.4 freezes only mature portable surfaces. Provisional/model-facing payloads
remain explicitly outside this set until they receive their own versioned
envelopes and conformance fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .active_state import ACTIVE_STATE_SCHEMA, ACTIVE_STATE_SCHEMA_VERSION
from .core.model import SEMANTIC_SCHEMA, SEMANTIC_SCHEMA_VERSION
from .core.ontology import CONFIDENCE_POLICY_VERSION
from .engine import ANALYSIS_CONTRACT_VERSION
from .grounding import GROUNDING_TOOL_CONTRACT_VERSION
from .snapshots import SNAPSHOT_SCHEMA, SNAPSHOT_SCHEMA_VERSION
from .tool_delivery import TOOL_SCHEMA_PACK, TOOL_SCHEMA_PACK_VERSION
from .tool_space import (
    TOOL_CAPABILITY_SCHEMA,
    TOOL_CAPABILITY_SCHEMA_VERSION,
    TOOL_CAPABILITY_SPACE_SCHEMA,
    TOOL_CAPABILITY_SPACE_SCHEMA_VERSION,
)


FROZEN_CONTRACT_SET_SCHEMA = "feynmap.substrate_contract_set"
FROZEN_CONTRACT_SET_VERSION = "1.0.0"


@dataclass(frozen=True)
class FrozenContract:
    key: str
    version: str
    category: str
    identifier: Optional[str] = None
    governed_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "key": self.key,
            "version": self.version,
            "category": self.category,
        }
        if self.identifier is not None:
            payload["identifier"] = self.identifier
        if self.governed_by is not None:
            payload["governed_by"] = self.governed_by
        return payload


FROZEN_SUBSTRATE_CONTRACTS: Tuple[FrozenContract, ...] = (
    FrozenContract(
        "semantic_graph",
        SEMANTIC_SCHEMA_VERSION,
        "canonical_truth",
        identifier=SEMANTIC_SCHEMA,
    ),
    FrozenContract(
        "analysis_contract",
        ANALYSIS_CONTRACT_VERSION,
        "semantic_policy",
        governed_by="semantic_graph",
    ),
    FrozenContract(
        "confidence_policy",
        CONFIDENCE_POLICY_VERSION,
        "semantic_policy",
        governed_by="semantic_graph",
    ),
    FrozenContract(
        "repository_snapshot",
        SNAPSHOT_SCHEMA_VERSION,
        "persistence",
        identifier=SNAPSHOT_SCHEMA,
    ),
    FrozenContract(
        "grounding_tool_catalog",
        GROUNDING_TOOL_CONTRACT_VERSION,
        "service_input",
    ),
    FrozenContract(
        "active_state",
        ACTIVE_STATE_SCHEMA_VERSION,
        "portable_agent_state",
        identifier=ACTIVE_STATE_SCHEMA,
    ),
    FrozenContract(
        "tool_capability",
        TOOL_CAPABILITY_SCHEMA_VERSION,
        "portable_tool_state",
        identifier=TOOL_CAPABILITY_SCHEMA,
    ),
    FrozenContract(
        "tool_capability_space",
        TOOL_CAPABILITY_SPACE_SCHEMA_VERSION,
        "portable_tool_state",
        identifier=TOOL_CAPABILITY_SPACE_SCHEMA,
    ),
    FrozenContract(
        "tool_schema_pack",
        TOOL_SCHEMA_PACK_VERSION,
        "model_tool_delivery",
        identifier=TOOL_SCHEMA_PACK,
    ),
)


PROVISIONAL_SUBSTRATE_SURFACES: Tuple[str, ...] = (
    "grounding_result_envelopes",
    "minimal_context",
    "sparse_context",
    "active_context",
    "integration_contract_wire_format",
    "judgment_wire_protocol",
)


def frozen_contract_manifest() -> Dict[str, Any]:
    """Return the machine-readable S6 frozen contract declaration."""

    return {
        "schema": FROZEN_CONTRACT_SET_SCHEMA,
        "schema_version": FROZEN_CONTRACT_SET_VERSION,
        "contracts": [contract.to_dict() for contract in FROZEN_SUBSTRATE_CONTRACTS],
        "provisional_surfaces": list(PROVISIONAL_SUBSTRATE_SURFACES),
        "compatibility_policy": "docs/S6_3_2_COMPATIBILITY_POLICY.md",
        "conformance_fixture": "tests/fixtures/contracts/s6_contracts_v1.json",
    }
