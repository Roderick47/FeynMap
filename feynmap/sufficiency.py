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
    novel_specific_term_count: int
    novel_max_specificity: float
    actionable_query_terms: int
    region_coverage: float
    marginal_gain: float
    marginal_gain_by_depth: Mapping[int, float]
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
            "novel_specific_term_count": int(self.novel_specific_term_count),
            "novel_max_specificity": float(self.novel_max_specificity),
            "actionable_query_terms": int(self.actionable_query_terms),
            "region_coverage": float(self.region_coverage),
            "marginal_gain": float(self.marginal_gain),
            "marginal_gain_by_depth": {
                str(depth): float(value)
                for depth, value in self.marginal_gain_by_depth.items()
            },
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
        min_query_coverage: float = 0.0,
        max_novel_region_gain: float = 1.0,
        min_score: float = 0.0,
        specific_term_threshold: float = 0.72,
        min_specific_novel_terms: int = 2,
        stalled_coverage_threshold: float = 0.18,
        stalled_marginal_threshold: float = 0.01,
    ) -> None:
        self.graph = graph
        self.region_index = region_index or RegionIndex(graph)
        self.min_query_coverage = max(0.0, min(1.0, float(min_query_coverage)))
        self.max_novel_region_gain = max(0.0, min(1.0, float(max_novel_region_gain)))
        self.min_score = max(0.0, min(1.0, float(min_score)))
        self.specific_term_threshold = max(
            0.0,
            min(1.0, float(specific_term_threshold)),
        )
        self.min_specific_novel_terms = max(1, int(min_specific_novel_terms))
        self.stalled_coverage_threshold = max(
            0.0,
            min(1.0, float(stalled_coverage_threshold)),
        )
        self.stalled_marginal_threshold = max(
            0.0,
            min(1.0, float(stalled_marginal_threshold)),
        )

    def evaluate(
        self,
        query: str,
        result: GuidedSearchResult,
        route: RegionRouteResult,
    ) -> SufficiencyResult:
        raw_query_terms = _tokens(query)
        # A prose token is only actionable if it occurs somewhere in the
        # grounded region index. This removes language-specific stop-word
        # assumptions and prevents ordinary connective prose from being scored
        # as missing repository knowledge.
        query_terms = {
            token
            for token in raw_query_terms
            if self.region_index.document_frequency.get(token, 0) > 0
        }
        activated_terms: Set[str] = set()
        activated_regions: Set[str] = set()
        for hit in result.hits:
            activated_terms.update(_node_terms(hit.node))
            region = self.region_index.region_for_node(hit.node.id)
            if region:
                activated_regions.add(region)

        def weight(term: str) -> float:
            return self.region_index._idf(term)

        total_weight = sum(weight(term) for term in query_terms)
        covered = query_terms & activated_terms
        uncovered = query_terms - activated_terms
        covered_weight = sum(weight(term) for term in covered)
        query_coverage = (
            covered_weight / total_weight
            if total_weight > 0.0
            else 1.0
        )

        selected_regions = list(route.selected_regions)
        region_coverage = (
            float(sum(1 for item in selected_regions if item in activated_regions))
            / float(len(selected_regions))
            if selected_regions
            else 1.0
        )

        # Estimate marginal global value from the actual representative nodes
        # that would be activated, not the union of every term in a whole file.
        representative_ids = self.region_index.seed_nodes(
            query,
            route,
            per_region=1,
            total_limit=max(1, len(selected_regions)),
        )
        novel_terms: Set[str] = set()
        for node_id in representative_ids:
            region_id = self.region_index.region_for_node(node_id)
            if region_id in activated_regions:
                continue
            node = self.graph.node(node_id)
            if node is None:
                continue
            novel_terms.update(uncovered & _node_terms(node))
        novel_weight = sum(weight(term) for term in novel_terms)
        novel_region_gain = (
            novel_weight / total_weight
            if total_weight > 0.0
            else 0.0
        )

        max_idf = self.region_index._idf("__term_absent_from_all_regions__")
        novel_specificities = {
            term: (
                weight(term) / max_idf
                if max_idf > 0.0
                else 0.0
            )
            for term in novel_terms
        }
        novel_specific_term_count = sum(
            1
            for value in novel_specificities.values()
            if value >= self.specific_term_threshold
        )
        novel_max_specificity = max(
            novel_specificities.values(),
            default=0.0,
        )

        marginal_gain_by_depth = self._marginal_gain_by_depth(
            query_terms,
            result,
            weight,
        )
        marginal_gain = (
            marginal_gain_by_depth[max(marginal_gain_by_depth)]
            if marginal_gain_by_depth
            else 0.0
        )
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
        # Exact lexical coverage is diagnostic, not a hard gate: FeynMap nodes
        # are intentionally compact and do not repeat all source prose.
        if (
            novel_specific_term_count >= self.min_specific_novel_terms
        ):
            reasons.append("specific_novel_region_information")
        if (
            query_coverage < self.stalled_coverage_threshold
            and marginal_gain <= self.stalled_marginal_threshold
        ):
            reasons.append("low_coverage_stalled")
        if (
            self.min_query_coverage > 0.0
            and query_coverage < self.min_query_coverage
        ):
            reasons.append("query_coverage")
        if (
            self.max_novel_region_gain < 1.0
            and novel_region_gain > self.max_novel_region_gain
        ):
            reasons.append("novel_region_information")
        if self.min_score > 0.0 and score < self.min_score:
            reasons.append("combined_score")

        sufficient = not reasons
        return SufficiencyResult(
            sufficient=sufficient,
            score=score,
            query_coverage=query_coverage,
            novel_region_gain=novel_region_gain,
            novel_specific_term_count=novel_specific_term_count,
            novel_max_specificity=novel_max_specificity,
            actionable_query_terms=len(query_terms),
            region_coverage=region_coverage,
            marginal_gain=marginal_gain,
            marginal_gain_by_depth=marginal_gain_by_depth,
            frontier_pressure=frontier_pressure,
            reasons=tuple(reasons),
            uncovered_query_terms=tuple(sorted(uncovered)),
            novel_region_terms=tuple(sorted(novel_terms)),
        )

    @staticmethod
    def _marginal_gain_by_depth(
        query_terms: Set[str],
        result: GuidedSearchResult,
        weight,
    ) -> Dict[int, float]:
        if not query_terms or not result.hits:
            return {}
        denominator = sum(weight(term) for term in query_terms)
        if denominator <= 0.0:
            return {}

        cumulative: Set[str] = set()
        gains: Dict[int, float] = {}
        depths = sorted({hit.depth for hit in result.hits})
        for depth in depths:
            depth_terms: Set[str] = set()
            for hit in result.hits:
                if hit.depth == depth:
                    depth_terms.update(_node_terms(hit.node))
            new_terms = (depth_terms - cumulative) & query_terms
            gains[depth] = (
                sum(weight(term) for term in new_terms) / denominator
            )
            cumulative.update(depth_terms)
        return gains

    @staticmethod
    def _frontier_pressure(result: GuidedSearchResult) -> float:
        if not result.trace:
            return 0.0
        step = result.trace[-1]
        if not step.candidates:
            return 0.0
        dropped = max(0, len(step.candidates) - len(step.selected))
        return float(dropped) / float(len(step.candidates))
