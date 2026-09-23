"""Adaptive JEV-guided search over the deterministic FeynMap graph.

This module keeps graph truth and probabilistic search policy separate:
FeynMap owns nodes, edges, evidence, and traversal bounds; a JudgmentProvider
only decides which grounded candidates are most relevant to explore next.

The search state in this module is intentionally ephemeral per invocation.
Persistent search memory, post-search confidence calibration, and hierarchical
final-candidate analysis belong to later layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..core import EdgeKind, SemanticEdge, SemanticGraph, SemanticNode
from ..query import FeynMapQuery
from .contracts import JudgmentProvider, JudgmentQuestion, JudgmentResult


_DIRECTION_VALUES = {"both", "outgoing", "incoming"}


@dataclass(frozen=True)
class SearchHit:
    node: SemanticNode
    depth: int
    parent_id: Optional[str] = None
    via_edge_id: Optional[str] = None
    search_probability: Optional[float] = None
    seed_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "node": self.node.to_dict(),
            "depth": int(self.depth),
        }
        if self.parent_id is not None:
            payload["parent_id"] = self.parent_id
        if self.via_edge_id is not None:
            payload["via_edge_id"] = self.via_edge_id
        if self.search_probability is not None:
            payload["search_probability"] = float(self.search_probability)
        if self.seed_score is not None:
            payload["seed_score"] = float(self.seed_score)
        return payload


@dataclass(frozen=True)
class SearchStep:
    depth: int
    frontier: Sequence[str]
    candidates: Sequence[str]
    selected: Sequence[str]
    probabilities: Mapping[str, float] = field(default_factory=dict)
    request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "depth": int(self.depth),
            "frontier": list(self.frontier),
            "candidates": list(self.candidates),
            "selected": list(self.selected),
            "probabilities": dict(self.probabilities),
        }
        if self.request_id:
            payload["request_id"] = self.request_id
        return payload


@dataclass(frozen=True)
class GuidedSearchResult:
    mode: str
    query: str
    roots: Sequence[SemanticNode]
    hits: Sequence[SearchHit]
    edges: Sequence[SemanticEdge]
    trace: Sequence[SearchStep]
    provider: Optional[str]
    model: Optional[str]
    exhausted: bool
    truncated: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "roots": [node.to_dict() for node in self.roots],
            "hits": [hit.to_dict() for hit in self.hits],
            "edges": [edge.to_dict() for edge in self.edges],
            "trace": [step.to_dict() for step in self.trace],
            "provider": self.provider,
            "model": self.model,
            "exhausted": bool(self.exhausted),
            "truncated": bool(self.truncated),
            "stats": {
                "root_count": len(self.roots),
                "hit_count": len(self.hits),
                "edge_count": len(self.edges),
                "search_steps": len(self.trace),
            },
        }


class JevGuidedSearch:
    """Bounded adaptive search over a FeynMap SemanticGraph.

    The provider is optional. Without one, the engine falls back to deterministic
    lexical/graph order, which makes tests and offline use reproducible.
    """

    def __init__(self, graph: SemanticGraph, provider: Optional[JudgmentProvider] = None) -> None:
        self.graph = graph
        self.provider = provider
        self.query = FeynMapQuery(graph)

    def from_node(
        self,
        node: str,
        goal: str,
        *,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
        relationship_kinds: Optional[Sequence[EdgeKind]] = None,
    ) -> GuidedSearchResult:
        """Search outward from one grounded node toward a task/concept goal."""
        root = self.query.resolve(node)
        return self._adaptive_search(
            mode="node",
            query=goal,
            roots=[root],
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
            relationship_kinds=relationship_kinds,
        )

    def concept(
        self,
        concept: str,
        *,
        seed_limit: int = 8,
        candidate_limit: int = 64,
        max_depth: int = 3,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
        relationship_kinds: Optional[Sequence[EdgeKind]] = None,
    ) -> GuidedSearchResult:
        """Find graph seeds for a concept, then adaptively explore from them."""
        concept = self._require_text(concept, "concept")
        candidate_limit = max(1, int(candidate_limit))
        seed_limit = max(1, int(seed_limit))

        lexical = self._concept_candidates(concept, candidate_limit)
        if not lexical:
            return GuidedSearchResult(
                mode="concept",
                query=concept,
                roots=[],
                hits=[],
                edges=[],
                trace=[],
                provider=self.provider.name if self.provider is not None else None,
                model=None,
                exhausted=True,
                truncated=False,
            )

        seed_nodes, seed_probabilities, seed_result = self._select_candidates(
            query=concept,
            anchor=None,
            candidates=[item[1] for item in lexical],
            limit=min(seed_limit, len(lexical)),
            phase="concept_seed",
            deterministic_scores={item[1].id: item[0] for item in lexical},
        )
        result = self._adaptive_search(
            mode="concept",
            query=concept,
            roots=seed_nodes,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
            relationship_kinds=relationship_kinds,
            seed_scores={item[1].id: item[0] for item in lexical},
            seed_probabilities=seed_probabilities,
        )
        if seed_result is None:
            return result

        seed_step = SearchStep(
            depth=0,
            frontier=[],
            candidates=[item[1].id for item in lexical],
            selected=[node.id for node in seed_nodes],
            probabilities=seed_probabilities,
            request_id=seed_result.request_id,
        )
        return GuidedSearchResult(
            mode=result.mode,
            query=result.query,
            roots=result.roots,
            hits=result.hits,
            edges=result.edges,
            trace=[seed_step] + list(result.trace),
            provider=result.provider,
            model=result.model or seed_result.model,
            exhausted=result.exhausted,
            truncated=result.truncated,
        )

    def _adaptive_search(
        self,
        *,
        mode: str,
        query: str,
        roots: Sequence[SemanticNode],
        max_depth: int,
        beam_width: int,
        max_nodes: int,
        direction: str,
        relationship_kinds: Optional[Sequence[EdgeKind]],
        seed_scores: Optional[Mapping[str, float]] = None,
        seed_probabilities: Optional[Mapping[str, float]] = None,
    ) -> GuidedSearchResult:
        query = self._require_text(query, "query")
        max_depth = max(0, int(max_depth))
        beam_width = max(1, int(beam_width))
        max_nodes = max(1, int(max_nodes))
        direction = str(direction).strip().lower()
        if direction not in _DIRECTION_VALUES:
            raise ValueError("direction must be one of: both, outgoing, incoming")

        kind_filter = set(relationship_kinds) if relationship_kinds is not None else None
        visited: Set[str] = set(node.id for node in roots)
        hits: List[SearchHit] = []
        for node in roots:
            hits.append(
                SearchHit(
                    node=node,
                    depth=0,
                    search_probability=(seed_probabilities or {}).get(node.id),
                    seed_score=(seed_scores or {}).get(node.id),
                )
            )

        selected_edges: Dict[str, SemanticEdge] = {}
        trace: List[SearchStep] = []
        frontier = list(roots)
        truncated = False
        last_model: Optional[str] = None

        for depth in range(1, max_depth + 1):
            if not frontier or len(hits) >= max_nodes:
                break

            parents: Dict[str, Tuple[str, SemanticEdge]] = {}
            candidates: Dict[str, SemanticNode] = {}
            for parent in frontier:
                for edge, neighbor in self._neighbors(parent.id, direction, kind_filter):
                    if neighbor.id in visited or neighbor.id in candidates:
                        continue
                    candidates[neighbor.id] = neighbor
                    parents[neighbor.id] = (parent.id, edge)

            if not candidates:
                frontier = []
                break

            available = max_nodes - len(hits)
            limit = min(beam_width, available, len(candidates))
            chosen, probabilities, judgment = self._select_candidates(
                query=query,
                anchor=frontier,
                candidates=list(candidates.values()),
                limit=limit,
                phase="frontier",
            )
            if judgment is not None:
                last_model = judgment.model or last_model

            selected_ids = [node.id for node in chosen]
            trace.append(
                SearchStep(
                    depth=depth,
                    frontier=[node.id for node in frontier],
                    candidates=sorted(candidates),
                    selected=selected_ids,
                    probabilities=probabilities,
                    request_id=judgment.request_id if judgment is not None else None,
                )
            )

            if len(chosen) < len(candidates):
                truncated = True

            next_frontier: List[SemanticNode] = []
            for chosen_node in chosen:
                parent_id, edge = parents[chosen_node.id]
                visited.add(chosen_node.id)
                selected_edges[edge.id] = edge
                hits.append(
                    SearchHit(
                        node=chosen_node,
                        depth=depth,
                        parent_id=parent_id,
                        via_edge_id=edge.id,
                        search_probability=probabilities.get(chosen_node.id),
                    )
                )
                next_frontier.append(chosen_node)
            frontier = next_frontier

        exhausted = not frontier
        if len(hits) >= max_nodes:
            truncated = True

        return GuidedSearchResult(
            mode=mode,
            query=query,
            roots=list(roots),
            hits=hits,
            edges=list(selected_edges.values()),
            trace=trace,
            provider=self.provider.name if self.provider is not None else None,
            model=last_model,
            exhausted=exhausted,
            truncated=truncated,
        )

    def _select_candidates(
        self,
        *,
        query: str,
        anchor: Optional[Sequence[SemanticNode]],
        candidates: Sequence[SemanticNode],
        limit: int,
        phase: str,
        deterministic_scores: Optional[Mapping[str, float]] = None,
    ) -> Tuple[List[SemanticNode], Dict[str, float], Optional[JudgmentResult]]:
        if not candidates or limit <= 0:
            return [], {}, None

        fallback = sorted(
            candidates,
            key=lambda node: (
                -float((deterministic_scores or {}).get(node.id, 0.0)),
                -float(node.confidence),
                node.id,
            ),
        )
        if self.provider is None:
            return fallback[:limit], {}, None

        state = {
            "phase": phase,
            "goal": query,
            "anchor": [self._node_summary(node) for node in (anchor or [])],
            "candidates": [self._node_summary(node) for node in candidates],
            "rules": {
                "graph_truth": "Candidates and relationships are grounded FeynMap facts.",
                "judgment_scope": "Judge search relevance only; do not reinterpret evidence confidence.",
                "unknown": "Missing graph relationships are unknown, not proof of impossibility.",
            },
        }
        questions: Dict[str, JudgmentQuestion] = {}
        key_to_id: Dict[str, str] = {}
        for index, node in enumerate(candidates):
            key = "candidate_%d" % index
            key_to_id[key] = node.id
            questions[key] = JudgmentQuestion.noul(
                "Given the search goal and grounded anchor, is candidate id %r useful to explore next? "
                "Judge only whether inspecting this candidate is likely to advance the targeted search."
                % node.id
            )

        result = self.provider.evaluate(state, questions)
        probabilities: Dict[str, float] = {}
        for key, node_id in key_to_id.items():
            value = max(0.0, min(1.0, float(result.answers[key].value)))
            probabilities[node_id] = value

        ranked = sorted(
            candidates,
            key=lambda node: (
                -probabilities[node.id],
                -float((deterministic_scores or {}).get(node.id, 0.0)),
                -float(node.confidence),
                node.id,
            ),
        )
        return ranked[:limit], probabilities, result

    def _neighbors(
        self,
        node_id: str,
        direction: str,
        kind_filter: Optional[Set[EdgeKind]],
    ) -> Iterable[Tuple[SemanticEdge, SemanticNode]]:
        edges: List[SemanticEdge] = []
        if direction in {"both", "outgoing"}:
            edges.extend(self.graph.outgoing(node_id))
        if direction in {"both", "incoming"}:
            edges.extend(self.graph.incoming(node_id))

        seen_edges: Set[str] = set()
        for edge in sorted(edges, key=lambda item: (item.kind.value, item.source, item.target, item.id)):
            if edge.id in seen_edges:
                continue
            seen_edges.add(edge.id)
            if kind_filter is not None and edge.kind not in kind_filter:
                continue
            neighbor_id = edge.target if edge.source == node_id else edge.source
            neighbor = self.graph.node(neighbor_id)
            if neighbor is not None:
                yield edge, neighbor

    def _concept_candidates(self, concept: str, limit: int) -> List[Tuple[float, SemanticNode]]:
        tokens = self._tokens(concept)
        scored: List[Tuple[float, SemanticNode]] = []
        for node in self.graph.nodes:
            haystack = " ".join(
                [
                    node.id,
                    node.name,
                    node.qualified_name or "",
                    node.kind.value,
                    node.language or "",
                    node.framework or "",
                    " ".join(str(value) for value in node.attributes.values() if isinstance(value, (str, int, float, bool))),
                ]
            ).casefold()
            if not tokens:
                score = 0.0
            else:
                matches = sum(1 for token in tokens if token in haystack)
                phrase_bonus = 1.0 if concept.casefold() in haystack else 0.0
                exact_bonus = 1.0 if concept.casefold() in {
                    node.id.casefold(),
                    node.name.casefold(),
                    (node.qualified_name or "").casefold(),
                } else 0.0
                score = (matches / float(len(tokens))) + phrase_bonus + exact_bonus
            if score > 0.0:
                scored.append((score, node))

        scored.sort(key=lambda item: (-item[0], -item[1].confidence, item[1].id))
        return scored[:limit]

    @staticmethod
    def _tokens(value: str) -> List[str]:
        cleaned = "".join(character.casefold() if character.isalnum() else " " for character in value)
        return [token for token in cleaned.split() if token]

    @staticmethod
    def _node_summary(node: SemanticNode) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": node.id,
            "name": node.name,
            "kind": node.kind.value,
            "confidence": round(float(node.confidence), 4),
            "confidence_tier": node.confidence_tier.value,
        }
        if node.qualified_name:
            payload["qualified_name"] = node.qualified_name
        if node.language:
            payload["language"] = node.language
        if node.framework:
            payload["framework"] = node.framework
        if node.location:
            payload["location"] = node.location.to_dict()
        return payload

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s must be a non-empty string" % label)
        return value.strip()
