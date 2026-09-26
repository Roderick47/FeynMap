"""Provider-neutral tool capability nodes for sparse tool-space routing.

S5 keeps tool capabilities separate from the repository semantic graph. The
repository graph owns software truth; this module owns a small routable view of
tool contracts that can later be selected before schemas are exposed to a
downstream model.

Capability nodes are derived only from declared tool contracts. They do not
invent effects, permissions, or semantic relationships.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Tuple


TOOL_CAPABILITY_SCHEMA = "feynmap.tool_capability"
TOOL_CAPABILITY_SCHEMA_VERSION = "1.0.0"


class ToolContract(Protocol):
    name: str
    description: str
    input_schema: Mapping[str, Any]
    read_only: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _contract_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _tokens(value: str) -> Tuple[str, ...]:
    cleaned = "".join(
        character.casefold() if character.isalnum() else " "
        for character in str(value or "")
    )
    seen = set()
    result = []
    for token in cleaned.split():
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return tuple(result)


def _schema_terms(schema: Mapping[str, Any]) -> Tuple[str, ...]:
    values = []
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name in sorted(str(key) for key in properties):
            values.append(name)
            rule = properties.get(name)
            if not isinstance(rule, Mapping):
                continue
            enum = rule.get("enum")
            if isinstance(enum, (list, tuple)):
                values.extend(str(item) for item in enum)
    return _tokens(" ".join(values))


@dataclass(frozen=True)
class ToolCapabilityNode:
    """One stable, grounded routing entity derived from a tool contract."""

    id: str
    namespace: str
    name: str
    description: str
    input_schema: Mapping[str, Any]
    read_only: bool
    contract_version: str
    contract_digest: str
    terms: Tuple[str, ...]
    required_inputs: Tuple[str, ...]
    optional_inputs: Tuple[str, ...]

    @classmethod
    def from_contract(
        cls,
        tool: ToolContract,
        *,
        namespace: str,
        contract_version: str,
    ) -> "ToolCapabilityNode":
        namespace = str(namespace).strip()
        if not namespace:
            raise ValueError("tool namespace is required")
        name = str(tool.name).strip()
        if not name:
            raise ValueError("tool name is required")

        schema = dict(tool.input_schema)
        properties = schema.get("properties")
        property_names = (
            tuple(sorted(str(key) for key in properties))
            if isinstance(properties, Mapping)
            else ()
        )
        required_raw = schema.get("required")
        required = tuple(
            sorted(
                str(item)
                for item in required_raw
                if str(item) in set(property_names)
            )
        ) if isinstance(required_raw, (list, tuple)) else ()
        required_set = set(required)
        optional = tuple(
            name for name in property_names
            if name not in required_set
        )

        declared = {
            "namespace": namespace,
            "name": name,
            "description": str(tool.description),
            "input_schema": schema,
            "read_only": bool(tool.read_only),
            "contract_version": str(contract_version),
        }
        terms = _tokens(
            "%s %s %s"
            % (
                name,
                tool.description,
                " ".join(_schema_terms(schema)),
            )
        )
        return cls(
            id="tool:%s:%s" % (namespace, name),
            namespace=namespace,
            name=name,
            description=str(tool.description),
            input_schema=schema,
            read_only=bool(tool.read_only),
            contract_version=str(contract_version),
            contract_digest=_contract_digest(declared),
            terms=terms,
            required_inputs=required,
            optional_inputs=optional,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": TOOL_CAPABILITY_SCHEMA,
            "schema_version": TOOL_CAPABILITY_SCHEMA_VERSION,
            "id": self.id,
            "namespace": self.namespace,
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "read_only": self.read_only,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
            "terms": list(self.terms),
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
        }


@dataclass(frozen=True)
class ToolCapabilitySpace:
    """Deterministic collection of tool capability nodes.

    S5.2 intentionally provides no ranking or selection behavior. S5.3 can
    consume this space without changing the underlying tool contracts.
    """

    namespace: str
    contract_version: str
    nodes: Tuple[ToolCapabilityNode, ...]

    @classmethod
    def from_contracts(
        cls,
        tools: Sequence[ToolContract],
        *,
        namespace: str,
        contract_version: str,
    ) -> "ToolCapabilitySpace":
        nodes = tuple(
            ToolCapabilityNode.from_contract(
                tool,
                namespace=namespace,
                contract_version=contract_version,
            )
            for tool in tools
        )
        ids = [node.id for node in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate tool capability ids are not allowed")
        return cls(
            namespace=str(namespace),
            contract_version=str(contract_version),
            nodes=tuple(sorted(nodes, key=lambda item: item.id)),
        )

    def node(self, value: str) -> Optional[ToolCapabilityNode]:
        needle = str(value)
        for node in self.nodes:
            if needle in {node.id, node.name}:
                return node
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "feynmap.tool_capability_space",
            "schema_version": TOOL_CAPABILITY_SCHEMA_VERSION,
            "namespace": self.namespace,
            "contract_version": self.contract_version,
            "tool_count": len(self.nodes),
            "nodes": [node.to_dict() for node in self.nodes],
        }
