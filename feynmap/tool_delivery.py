"""Bounded delivery of grounded tool schemas selected by S5 routing.

This module turns a sufficient S5.4 routing result into the small, portable
tool catalog supplied to a downstream model. It does not execute tools or
measure routing quality.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from .tool_routing import ToolRoutingResult
from .tool_space import ToolCapabilityNode, ToolCapabilitySpace


TOOL_SCHEMA_PACK = "feynmap.tool_schema_pack"
TOOL_SCHEMA_PACK_VERSION = "1.0.0"


@dataclass(frozen=True)
class DeliveredToolSchema:
    """One grounded contract prepared for downstream model delivery."""

    tool_id: str
    name: str
    description: str
    input_schema: Mapping[str, Any]
    read_only: bool
    contract_version: str
    contract_digest: str

    @classmethod
    def from_node(cls, node: ToolCapabilityNode) -> "DeliveredToolSchema":
        return cls(
            tool_id=node.id,
            name=node.name,
            description=node.description,
            input_schema=copy.deepcopy(dict(node.input_schema)),
            read_only=node.read_only,
            contract_version=node.contract_version,
            contract_digest=node.contract_digest,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(dict(self.input_schema)),
            "read_only": self.read_only,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True)
class ToolSchemaPack:
    """Portable schema subset produced from one routing decision."""

    query: str
    route_sufficient: bool
    route_reason: str
    available_tool_count: int
    selected_tool_count: int
    tools: Tuple[DeliveredToolSchema, ...]

    @property
    def delivery_ratio(self) -> float:
        if self.available_tool_count <= 0:
            return 0.0
        return float(len(self.tools)) / float(self.available_tool_count)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": TOOL_SCHEMA_PACK,
            "schema_version": TOOL_SCHEMA_PACK_VERSION,
            "query": self.query,
            "route_sufficient": self.route_sufficient,
            "route_reason": self.route_reason,
            "available_tool_count": self.available_tool_count,
            "selected_tool_count": self.selected_tool_count,
            "delivered_tool_count": len(self.tools),
            "delivery_ratio": self.delivery_ratio,
            "tools": [tool.to_dict() for tool in self.tools],
        }


class ToolSchemaPacker:
    """Expose schemas only for a sufficient, grounded routing result."""

    def __init__(self, space: ToolCapabilitySpace, *, max_tools: int = 4) -> None:
        if isinstance(max_tools, bool) or not isinstance(max_tools, int) or max_tools < 1:
            raise ValueError("max_tools must be a positive integer")
        self.space = space
        self.max_tools = max_tools
        self._nodes = {node.id: node for node in space.nodes}

    def pack(self, routing: ToolRoutingResult) -> ToolSchemaPack:
        if not isinstance(routing, ToolRoutingResult):
            raise TypeError("routing must be a ToolRoutingResult")

        selection = routing.selection
        if selection.candidate_count != len(self.space.nodes):
            raise ValueError("routing result belongs to a different capability space")

        selected_nodes = []
        seen = set()
        for hit in selection.hits:
            grounded = self._nodes.get(hit.node.id)
            if grounded is None or grounded.contract_digest != hit.node.contract_digest:
                raise ValueError("routing result contains an ungrounded tool capability")
            if grounded.id in seen:
                raise ValueError("routing result contains duplicate tool capabilities")
            seen.add(grounded.id)
            selected_nodes.append(grounded)

        if not routing.sufficient:
            delivered = ()
        else:
            delivered = tuple(
                DeliveredToolSchema.from_node(node)
                for node in selected_nodes[:self.max_tools]
            )

        return ToolSchemaPack(
            query=selection.query,
            route_sufficient=routing.sufficient,
            route_reason=routing.reason,
            available_tool_count=len(self.space.nodes),
            selected_tool_count=len(selected_nodes),
            tools=delivered,
        )
