"""Provider-neutral sufficiency and adaptive-effort signals.

Sufficiency never decides graph truth. It inspects an already-grounded search
result plus a cheap region route and decides whether more retrieval is likely
to add task-relevant information.

The policy is intentionally deterministic and inspectable. It can be used
before any JEV/LLM judgment call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .core import SemanticGraph, SemanticNode
from .judgment.search import GuidedSearchResult
from .routing import RegionIndex, RegionRouteResult


def _tokens(value: str) -> Set[str]:
    cleaned = "".join(
        character.casefold() if character.isalnum() else " "
        for character in str(value or "")
    )
    return {token for token in cleaned.split() if len(token) >= 3}


def _flatten(value: Any, depth: int = 0) -> Iterable[str]:
    if depth > 2:
        return
    if isinstance(value, (str, int, float, bool)):
        yield str(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            for text in _flatten(item, depth + 1):
                yield text
        return
    if isinstance(value, (list, tuple, set)):
        for item in list(value)[:32]:
            for text in _flatten(item, depth + 1):
                yield text


def _node_terms(node: SemanticNode) -> Set[str]:
    values: List[str] = [
        node.id,
        node.name,
        node.qualified_name or "",
        node.kind.value,
        node.language or "",
        node.framework or "",
        node.location.path if node.location else "",
    ]
    values.extend(_flatten(node.attributes))
    return _tokens(" ".join(values))


@dataclass(frozen=True)
class SufficiencyResult:
    sufficient: bool
    score: float
    query_coverage: float
    novel_region_gain: float
    region_coverage: float
    marginal_gain: float
    frontier_pressure: float
    reasons: Sequence[str]
    uncovered_query_terms: Sequence[str]
    novel_region_terms: Sequence[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sufficient": bool(self.sufficient),
            "score": float(self.score),
            "query_coverage": float(self.query_coverage),
            "novel_region_gain": float(self.novel_region_gain),
            "region_coverage": float(self.region_coverage),
            "marginal_gain": float(self.marginal_gain),
            "frontier_pressure": float(self.frontier_pressure),
            "reasons": list(self.reasons),
            "uncovered_query_terms": list(self.uncovered_query_terms),
            "novel_region_terms": list(self.novel_region_terms),
        }


class SufficiencyEvaluator:
    """Cheap deterministic stop/escalate policy.

    The evaluator favors stopping only when local activation already covers the
    task vocabulary and the cheap global region route has little uncovered
    query information to contribute.
    """

    def __init__(
        self,
        graph: SemanticGraph,
        region_index: Optional[RegionIndex] = None,
        *,
        min_query_coverage: float = 0.60,
        max_novel_region_gain: float = 0.0,
        min_score: float = 0.62,
    ) -> None:
        self.graph = graph
        self.region_index = region_index or RegionIndex(graph)
        self.min_query_coverage = max(0.0, min(1.0, float(min_query_coverage)))
        self.max_novel_region_gain = max(0.0, min(1.0, float(max_novel_region_gain)))
        self.min_score = max(0.0, min(1.0, float(min_score)))

    def evaluate(
        self,
        query: str,
        result: GuidedSearchResult,
        route: RegionRouteResult,
    ) -> SufficiencyResult:
        query_terms = _tokens(query)
        activated_terms: Set[str] = set()
        activated_regions: Set[str] = set()
        for hit in result.hits:
            activated_terms.update(_node_terms(hit.node))
            region = self.region_index.region_for_node(hit.node.id)
            if region:
                activated_regions.add(region)

        covered = query_terms & activated_terms
        uncovered = query_terms - activated_terms
        query_coverage = (
            float(len(covered)) / float(len(query_terms))
            if query_terms
            else 1.0
        )

        selected_regions = list(route.selected_regions)
        region_coverage = (
            float(sum(1 for item in selected_regions if item in activated_regions))
            / float(len(selected_regions))
            if selected_regions
            else 1.0
        )

        novel_terms: Set[str] = set()
        for region_id in selected_regions:
            if region_id in activated_regions:
                continue
            region = self.region_index.regions.get(region_id)
            if region is None:
                continue
            novel_terms.update(uncovered & set(region.terms))
        novel_region_gain = (
            float(len(novel_terms)) / float(len(query_terms))
            if query_terms
            else 0.0
        )

        marginal_gain = self._marginal_gain(query_terms, result)
        frontier_pressure = self._frontier_pressure(result)

        # Weighted confidence-like sufficiency score. Query coverage and the
        # absence of globally discoverable missing query terms dominate.
        score = (
            (0.55 * query_coverage)
            + (0.20 * (1.0 - novel_region_gain))
            + (0.15 * region_coverage)
            + (0.10 * (1.0 - min(1.0, frontier_pressure)))
        )

        reasons: List[str] = []
        if query_coverage < self.min_query_coverage:
            reasons.append("query_coverage")
        if novel_region_gain > self.max_novel_region_gain:
            reasons.append("novel_region_information")
        if score < self.min_score:
            reasons.append("combined_score")

        sufficient = not reasons
        return SufficiencyResult(
            sufficient=sufficient,
            score=score,
            query_coverage=query_coverage,
            novel_region_gain=novel_region_gain,
            region_coverage=region_coverage,
            marginal_gain=marginal_gain,
            frontier_pressure=frontier_pressure,
            reasons=tuple(reasons),
            uncovered_query_terms=tuple(sorted(uncovered)),
            novel_region_terms=tuple(sorted(novel_terms)),
        )

    @staticmethod
    def _marginal_gain(query_terms: Set[str], result: GuidedSearchResult) -> float:
        if not query_terms or not result.hits:
            return 0.0
        max_depth = max(hit.depth for hit in result.hits)
        before_terms: Set[str] = set()
        last_terms: Set[str] = set()
        for hit in result.hits:
            if hit.depth < max_depth:
                before_terms.update(_node_terms(hit.node))
            elif hit.depth == max_depth:
                last_terms.update(_node_terms(hit.node))
        new_terms = (last_terms - before_terms) & query_terms
        return float(len(new_terms)) / float(len(query_terms))

    @staticmethod
    def _frontier_pressure(result: GuidedSearchResult) -> float:
        if not result.trace:
            return 0.0
        step = result.trace[-1]
        if not step.candidates:
            return 0.0
        dropped = max(0, len(step.candidates) - len(step.selected))
        return float(dropped) / float(len(step.candidates))
