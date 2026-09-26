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
import math
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


TOOL_SELECTION_SCHEMA = "feynmap.tool_selection"
TOOL_SELECTION_SCHEMA_VERSION = "1.0.0"

_ROUTING_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "the", "to", "with",
}


def _routing_tokens(value: str) -> Tuple[str, ...]:
    return tuple(
        token
        for token in _tokens(value)
        if token not in _ROUTING_STOPWORDS
    )


@dataclass(frozen=True)
class ToolSelectionHit:
    """One deterministic tool-space routing result."""

    node: ToolCapabilityNode
    score: float
    matched_terms: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.node.id,
            "name": self.node.name,
            "score": float(self.score),
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class ToolSelectionResult:
    """Small ranked subset selected from a grounded capability space."""

    query: str
    candidate_count: int
    actionable_query_terms: Tuple[str, ...]
    hits: Tuple[ToolSelectionHit, ...]

    @property
    def selection_ratio(self) -> float:
        if self.candidate_count <= 0:
            return 0.0
        return float(len(self.hits)) / float(self.candidate_count)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": TOOL_SELECTION_SCHEMA,
            "schema_version": TOOL_SELECTION_SCHEMA_VERSION,
            "query": self.query,
            "candidate_count": int(self.candidate_count),
            "selected_count": len(self.hits),
            "selection_ratio": self.selection_ratio,
            "actionable_query_terms": list(self.actionable_query_terms),
            "hits": [hit.to_dict() for hit in self.hits],
        }


class DeterministicToolSelector:
    """Cheap provider-free lexical router over declared tool capabilities.

    S5.3 scores only terms grounded in the declared tool contracts. It does not
    invoke JEV, infer undeclared capabilities, or fall back to arbitrary tools
    when the query has no grounded lexical match.
    """

    def __init__(self, space: ToolCapabilitySpace) -> None:
        self.space = space
        self._document_frequency: Dict[str, int] = {}
        self._node_terms: Dict[str, frozenset] = {}
        for node in space.nodes:
            terms = frozenset(_routing_tokens(" ".join(node.terms)))
            self._node_terms[node.id] = terms
            for term in terms:
                self._document_frequency[term] = (
                    self._document_frequency.get(term, 0) + 1
                )

    def _idf(self, term: str) -> float:
        count = self._document_frequency.get(term, 0)
        return math.log(
            (len(self.space.nodes) + 1.0) / (count + 1.0)
        ) + 1.0

    def select(self, query: str, *, limit: int = 4) -> ToolSelectionResult:
        text = str(query).strip()
        if not text:
            raise ValueError("tool routing query is required")
        limit = max(1, int(limit))

        query_terms = set(_routing_tokens(text))
        actionable = tuple(sorted(
            term for term in query_terms
            if term in self._document_frequency
        ))

        ranked = []
        for node in self.space.nodes:
            terms = self._node_terms[node.id]
            overlap = set(actionable) & set(terms)
            if not overlap:
                continue

            name_terms = set(_routing_tokens(node.name))
            weighted = sum(
                self._idf(term) * (1.75 if term in name_terms else 1.0)
                for term in overlap
            )
            denominator = sum(
                self._idf(term) * 1.75
                for term in actionable
            )
            score = weighted / denominator if denominator > 0.0 else 0.0
            ranked.append((
                score,
                len(overlap),
                node.id,
                ToolSelectionHit(
                    node=node,
                    score=score,
                    matched_terms=tuple(sorted(overlap)),
                ),
            ))

        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        hits = tuple(item[3] for item in ranked[:limit])
        return ToolSelectionResult(
            query=text,
            candidate_count=len(self.space.nodes),
            actionable_query_terms=actionable,
            hits=hits,
        )
