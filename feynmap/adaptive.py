"""Adaptive sparse activation controller.

This layer owns effort allocation, not graph truth:
1. deterministic local traversal;
2. provider-neutral sufficiency check;
3. bounded region activation only when local context is insufficient;
4. optional JudgmentProvider/JEV escalation only when deterministic retrieval
   remains insufficient.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, Mapping, Optional, Sequence

from .core import SemanticGraph
from .judgment.contracts import JudgmentProvider
from .judgment.search import GuidedSearchResult, JevGuidedSearch
from .query import FeynMapQuery
from .routing import RegionIndex, RegionRouteResult, _merge_search_results
from .sufficiency import SufficiencyEvaluator, SufficiencyResult


@dataclass(frozen=True)
class AdaptiveSearchResult:
    search: GuidedSearchResult
    route: RegionRouteResult
    stage: str
    escalations: Sequence[str]
    local_sufficiency: SufficiencyResult
    final_sufficiency: SufficiencyResult
    timings_ms: Mapping[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "escalations": list(self.escalations),
            "route": self.route.to_dict(),
            "local_sufficiency": self.local_sufficiency.to_dict(),
            "final_sufficiency": self.final_sufficiency.to_dict(),
            "timings_ms": {
                key: float(value)
                for key, value in self.timings_ms.items()
            },
            "search": self.search.to_dict(),
        }


class AdaptiveSparseSearch:
    """Use the cheapest sufficient retrieval path for each task."""

    def __init__(
        self,
        graph: SemanticGraph,
        provider: Optional[JudgmentProvider] = None,
        *,
        region_limit: int = 8,
        region_seed_limit: int = 12,
        sufficiency: Optional[SufficiencyEvaluator] = None,
    ) -> None:
        self.graph = graph
        self.provider = provider
        self.query = FeynMapQuery(graph)
        self.index = RegionIndex(graph)
        self.local_searcher = JevGuidedSearch(graph, provider=None)
        self.provider_searcher = (
            JevGuidedSearch(graph, provider=provider)
            if provider is not None
            else None
        )
        self.region_limit = max(1, int(region_limit))
        self.region_seed_limit = max(1, int(region_seed_limit))
        self.sufficiency = sufficiency or SufficiencyEvaluator(
            graph,
            region_index=self.index,
        )

    def _activate_regions(
        self,
        local: GuidedSearchResult,
        query: str,
        route: RegionRouteResult,
        *,
        max_depth: int,
        beam_width: int,
        max_nodes: int,
        direction: str,
        region_seeds: Optional[Sequence[str]] = None,
    ) -> GuidedSearchResult:
        allowed = self.index.node_ids_for_regions(route.selected_regions)
        global_budget = max(4, min(16, max(4, int(max_nodes)) // 4))
        if region_seeds is None:
            region_seeds = self.index.seed_nodes(
                query,
                route,
                per_region=1,
                total_limit=min(
                    global_budget,
                    self.region_seed_limit,
                    max(1, len(route.selected_regions)),
                ),
            )
        if not region_seeds:
            return local

        global_result = self.local_searcher.from_roots(
            region_seeds,
            query,
            max_depth=min(1, max_depth),
            beam_width=min(4, beam_width),
            max_nodes=global_budget,
            direction=direction,
            allowed_node_ids=allowed,
        )
        return _merge_search_results(local, global_result, max_nodes=max_nodes)

    def from_node(
        self,
        node: str,
        goal: str,
        *,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> AdaptiveSearchResult:
        root = self.query.resolve(node)
        timings: Dict[str, float] = {}

        started = time.perf_counter()
        route = self.index.route(
            goal,
            anchor_node_id=root.id,
            limit=self.region_limit,
        )
        timings["route"] = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        local = self.local_searcher.from_node(
            root.id,
            goal,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        timings["local_search"] = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        global_budget = max(4, min(16, max(4, int(max_nodes)) // 4))
        region_seeds = self.index.seed_nodes(
            goal,
            route,
            per_region=1,
            total_limit=min(
                global_budget,
                self.region_seed_limit,
                max(1, len(route.selected_regions)),
            ),
        )
        local_sufficiency = self.sufficiency.evaluate(
            goal,
            local,
            route,
            representative_ids=region_seeds,
        )
        timings["sufficiency"] = (time.perf_counter() - started) * 1000.0
        if local_sufficiency.sufficient:
            return AdaptiveSearchResult(
                search=local,
                route=route,
                stage="local",
                escalations=(),
                local_sufficiency=local_sufficiency,
                final_sufficiency=local_sufficiency,
                timings_ms=timings,
            )

        started = time.perf_counter()
        region_search = self._activate_regions(
            local,
            goal,
            route,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
            region_seeds=region_seeds,
        )
        timings["region_search"] = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        region_sufficiency = self.sufficiency.evaluate(
            goal,
            region_search,
            route,
            representative_ids=region_seeds,
        )
        timings["post_region_sufficiency"] = (
            time.perf_counter() - started
        ) * 1000.0
        if region_sufficiency.sufficient or self.provider_searcher is None:
            return AdaptiveSearchResult(
                search=region_search,
                route=route,
                stage="region",
                escalations=("region",),
                local_sufficiency=local_sufficiency,
                final_sufficiency=region_sufficiency,
                timings_ms=timings,
            )

        started = time.perf_counter()
        judged = self.provider_searcher.from_node(
            root.id,
            goal,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        timings["jev_search"] = (time.perf_counter() - started) * 1000.0
        merged = _merge_search_results(
            region_search,
            judged,
            max_nodes=max_nodes,
        )
        final_sufficiency = self.sufficiency.evaluate(
            goal,
            merged,
            route,
            representative_ids=region_seeds,
        )
        return AdaptiveSearchResult(
            search=merged,
            route=route,
            stage="jev",
            escalations=("region", "jev"),
            local_sufficiency=local_sufficiency,
            final_sufficiency=final_sufficiency,
            timings_ms=timings,
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
    ) -> AdaptiveSearchResult:
        timings: Dict[str, float] = {}
        started = time.perf_counter()
        route = self.index.route(concept, limit=self.region_limit)
        timings["route"] = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        local = self.local_searcher.concept(
            concept,
            seed_limit=seed_limit,
            candidate_limit=candidate_limit,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        timings["local_search"] = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        region_seeds = self.index.seed_nodes(
            concept,
            route,
            per_region=1,
            total_limit=min(
                self.region_seed_limit,
                max(1, len(route.selected_regions)),
            ),
        )
        local_sufficiency = self.sufficiency.evaluate(
            concept,
            local,
            route,
            representative_ids=region_seeds,
        )
        timings["sufficiency"] = (time.perf_counter() - started) * 1000.0
        if local_sufficiency.sufficient or self.provider_searcher is None:
            return AdaptiveSearchResult(
                search=local,
                route=route,
                stage="local",
                escalations=(),
                local_sufficiency=local_sufficiency,
                final_sufficiency=local_sufficiency,
                timings_ms=timings,
            )

        started = time.perf_counter()
        judged = self.provider_searcher.concept(
            concept,
            seed_limit=seed_limit,
            candidate_limit=candidate_limit,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        timings["jev_search"] = (time.perf_counter() - started) * 1000.0
        final_sufficiency = self.sufficiency.evaluate(
            concept,
            judged,
            route,
            representative_ids=region_seeds,
        )
        return AdaptiveSearchResult(
            search=judged,
            route=route,
            stage="jev",
            escalations=("jev",),
            local_sufficiency=local_sufficiency,
            final_sufficiency=final_sufficiency,
            timings_ms=timings,
        )
