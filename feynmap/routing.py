"""Cheap hierarchical routing over FeynMap's canonical semantic graph.

The region index is deliberately deterministic and provider-free. It groups
grounded nodes by source file, builds compact lexical summaries, and uses an
IDF-weighted query match to select a small set of regions before deeper graph
search. JEV remains available downstream as the judgment policy.

This is the first S1 implementation: it is intentionally simple enough to
benchmark, inspect, and replace without changing graph truth.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .core import SemanticGraph, SemanticNode
from .judgment.search import GuidedSearchResult, JevGuidedSearch
from .query import FeynMapQuery


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "how", "if", "in", "into", "is", "it", "of", "on", "or", "should", "that",
    "the", "their", "then", "this", "to", "when", "where", "while", "with",
}


def _tokens(value: str) -> List[str]:
    cleaned = "".join(character.casefold() if character.isalnum() else " " for character in str(value or ""))
    return [token for token in cleaned.split() if token and token not in _STOPWORDS]


def _flatten_attribute_text(value: Any, depth: int = 0) -> Iterable[str]:
    if depth > 2:
        return
    if isinstance(value, (str, int, float, bool)):
        yield str(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            for text in _flatten_attribute_text(item, depth + 1):
                yield text
        return
    if isinstance(value, (list, tuple, set)):
        for item in list(value)[:32]:
            for text in _flatten_attribute_text(item, depth + 1):
                yield text


def _region_key(node: SemanticNode) -> str:
    if node.location and node.location.path:
        return str(node.location.path).replace("\\", "/")
    if node.qualified_name:
        parts = node.qualified_name.split(".")
        return "symbol:" + ".".join(parts[: max(1, min(3, len(parts)))])
    return "node:" + node.id


def _region_weight(region_id: str) -> float:
    normalized = region_id.casefold()
    if normalized.startswith(("symbol:", "node:")):
        return 0.15
    parts = normalized.replace("\\", "/").split("/")
    basename = parts[-1] if parts else normalized
    if "tests" in parts or basename.startswith("test_") or basename in {"tests.py", "test.py"}:
        return 0.45
    return 1.0


@dataclass(frozen=True)
class RegionSummary:
    id: str
    node_ids: Tuple[str, ...]
    terms: frozenset

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "node_count": len(self.node_ids),
        }


@dataclass(frozen=True)
class RegionRouteResult:
    query: str
    anchor_region: Optional[str]
    candidate_regions: int
    selected_regions: Tuple[str, ...]
    scores: Mapping[str, float]

    @property
    def region_touch_ratio(self) -> float:
        if self.candidate_regions <= 0:
            return 0.0
        return float(len(self.selected_regions)) / float(self.candidate_regions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "anchor_region": self.anchor_region,
            "candidate_regions": int(self.candidate_regions),
            "selected_regions": list(self.selected_regions),
            "selected_region_count": len(self.selected_regions),
            "region_touch_ratio": self.region_touch_ratio,
            "scores": {key: float(value) for key, value in self.scores.items()},
        }


@dataclass(frozen=True)
class RegionFirstSearchResult:
    search: GuidedSearchResult
    route: RegionRouteResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route.to_dict(),
            "search": self.search.to_dict(),
        }


class RegionIndex:
    """File/module-level summary index for cheap first-stage routing."""

    def __init__(self, graph: SemanticGraph) -> None:
        self.graph = graph
        grouped: Dict[str, List[SemanticNode]] = {}
        self.node_region: Dict[str, str] = {}
        for node in graph.nodes:
            key = _region_key(node)
            grouped.setdefault(key, []).append(node)
            self.node_region[node.id] = key

        summaries: Dict[str, RegionSummary] = {}
        document_frequency: Dict[str, int] = {}
        for key, nodes in grouped.items():
            terms: Set[str] = set(_tokens(key))
            for node in nodes:
                terms.update(_tokens(node.id))
                terms.update(_tokens(node.name))
                terms.update(_tokens(node.qualified_name or ""))
                terms.update(_tokens(node.kind.value))
                terms.update(_tokens(node.language or ""))
                terms.update(_tokens(node.framework or ""))
                for text in _flatten_attribute_text(node.attributes):
                    terms.update(_tokens(text))
            summary = RegionSummary(
                id=key,
                node_ids=tuple(sorted(node.id for node in nodes)),
                terms=frozenset(terms),
            )
            summaries[key] = summary
            for term in terms:
                document_frequency[term] = document_frequency.get(term, 0) + 1

        self.regions = summaries
        self.document_frequency = document_frequency
        self.adjacency: Dict[str, Set[str]] = {key: set() for key in summaries}
        for edge in graph.edges:
            source_region = self.node_region.get(edge.source)
            target_region = self.node_region.get(edge.target)
            if not source_region or not target_region or source_region == target_region:
                continue
            self.adjacency.setdefault(source_region, set()).add(target_region)
            self.adjacency.setdefault(target_region, set()).add(source_region)

    def region_for_node(self, node_id: str) -> Optional[str]:
        return self.node_region.get(node_id)

    def node_ids_for_regions(self, region_ids: Iterable[str]) -> Set[str]:
        result: Set[str] = set()
        for region_id in region_ids:
            region = self.regions.get(region_id)
            if region is not None:
                result.update(region.node_ids)
        return result

    def _idf(self, token: str) -> float:
        count = self.document_frequency.get(token, 0)
        return math.log((len(self.regions) + 1.0) / (count + 1.0)) + 1.0

    def route(
        self,
        query: str,
        *,
        anchor_node_id: Optional[str] = None,
        limit: int = 8,
    ) -> RegionRouteResult:
        query_tokens = set(_tokens(query))
        anchor_region = self.region_for_node(anchor_node_id) if anchor_node_id else None
        neighbor_regions = self.adjacency.get(anchor_region, set()) if anchor_region else set()

        scored: List[Tuple[float, str]] = []
        considered = 0
        denominator = sum(self._idf(token) for token in query_tokens) if query_tokens else 1.0
        for region_id, region in self.regions.items():
            weight = _region_weight(region_id)
            if weight < 0.2 and region_id != anchor_region:
                continue
            considered += 1
            lexical = sum(self._idf(token) for token in query_tokens if token in region.terms)
            if query_tokens:
                lexical /= denominator
            path_terms = set(_tokens(region_id))
            path_match = sum(self._idf(token) for token in query_tokens if token in path_terms)
            if query_tokens:
                path_match /= denominator
            lexical = (lexical + (1.5 * path_match)) * weight
            locality = 0.0
            if region_id == anchor_region:
                locality = 2.0
            elif region_id in neighbor_regions:
                locality = 0.10
            score = lexical + locality
            if score > 0.0:
                scored.append((score, region_id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        limit = max(1, int(limit))
        selected = [region_id for _, region_id in scored[:limit]]

        if anchor_region and anchor_region not in selected:
            selected.insert(0, anchor_region)
            selected = selected[:limit]

        if not selected and anchor_region:
            selected = [anchor_region]

        score_map = {region_id: score for score, region_id in scored if region_id in selected}
        if anchor_region in selected and anchor_region not in score_map:
            score_map[anchor_region] = 2.0

        return RegionRouteResult(
            query=str(query),
            anchor_region=anchor_region,
            candidate_regions=considered,
            selected_regions=tuple(selected),
            scores=score_map,
        )

    def seed_nodes(
        self,
        query: str,
        route: RegionRouteResult,
        *,
        per_region: int = 2,
        total_limit: int = 12,
    ) -> List[str]:
        query_tokens = set(_tokens(query))
        ranked: List[Tuple[float, str, str]] = []
        for region_id in route.selected_regions:
            region = self.regions[region_id]
            region_rows: List[Tuple[float, str]] = []
            for node_id in region.node_ids:
                node = self.graph.node(node_id)
                if node is None:
                    continue
                text = " ".join(
                    [
                        node.id,
                        node.name,
                        node.qualified_name or "",
                        node.kind.value,
                        node.location.path if node.location else "",
                        " ".join(_flatten_attribute_text(node.attributes)),
                    ]
                )
                terms = set(_tokens(text))
                score = sum(self._idf(token) for token in query_tokens if token in terms)
                if node.kind.value in {"file", "module"}:
                    score += 0.02
                region_rows.append((score, node_id))
            region_rows.sort(key=lambda item: (-item[0], item[1]))
            for score, node_id in region_rows[: max(1, int(per_region))]:
                ranked.append((score, region_id, node_id))

        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        result: List[str] = []
        seen: Set[str] = set()
        for _, _, node_id in ranked:
            if node_id in seen:
                continue
            seen.add(node_id)
            result.append(node_id)
            if len(result) >= max(1, int(total_limit)):
                break
        return result


def _merge_search_results(
    local: GuidedSearchResult,
    global_result: GuidedSearchResult,
    *,
    max_nodes: int,
) -> GuidedSearchResult:
    max_nodes = max(1, int(max_nodes))
    hits = []
    seen_nodes: Set[str] = set()
    for source in (local.hits, global_result.hits):
        for hit in source:
            if hit.node.id in seen_nodes:
                continue
            seen_nodes.add(hit.node.id)
            hits.append(hit)
            if len(hits) >= max_nodes:
                break
        if len(hits) >= max_nodes:
            break

    allowed_nodes = {hit.node.id for hit in hits}
    edges = []
    seen_edges: Set[str] = set()
    for source in (local.edges, global_result.edges):
        for edge in source:
            if edge.id in seen_edges:
                continue
            if edge.source not in allowed_nodes or edge.target not in allowed_nodes:
                continue
            seen_edges.add(edge.id)
            edges.append(edge)

    roots = []
    seen_roots: Set[str] = set()
    for source in (local.roots, global_result.roots):
        for node in source:
            if node.id in seen_roots or node.id not in allowed_nodes:
                continue
            seen_roots.add(node.id)
            roots.append(node)

    return GuidedSearchResult(
        mode="region_hybrid",
        query=local.query,
        roots=roots,
        hits=hits,
        edges=edges,
        trace=list(local.trace) + list(global_result.trace),
        provider=local.provider or global_result.provider,
        model=local.model or global_result.model,
        exhausted=local.exhausted and global_result.exhausted,
        truncated=local.truncated or global_result.truncated or len(allowed_nodes) >= max_nodes,
    )


class RegionFirstSearch:
    """Route to a small set of regions before bounded graph activation."""

    def __init__(
        self,
        graph: SemanticGraph,
        provider=None,
        *,
        region_limit: int = 8,
        seed_limit: int = 12,
    ) -> None:
        self.graph = graph
        self.query = FeynMapQuery(graph)
        self.index = RegionIndex(graph)
        self.searcher = JevGuidedSearch(graph, provider=provider)
        self.region_limit = max(1, int(region_limit))
        self.seed_limit = max(1, int(seed_limit))

    def from_node(
        self,
        node: str,
        goal: str,
        *,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> RegionFirstSearchResult:
        root = self.query.resolve(node)
        route = self.index.route(goal, anchor_node_id=root.id, limit=self.region_limit)

        # Channel 1 preserves ordinary grounded structural traversal. Region
        # routing must not erase a useful local path merely because lexical
        # summaries rank another region more highly.
        local = self.searcher.from_node(
            root.id,
            goal,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )

        # Channel 2 spends a small bounded budget on globally relevant regions.
        # This can recover useful knowledge when the current semantic graph is
        # missing a direct edge from the anchor path.
        allowed = self.index.node_ids_for_regions(route.selected_regions)
        global_budget = max(4, min(16, max(4, int(max_nodes)) // 4))
        global_result = self.searcher.concept(
            goal,
            seed_limit=min(4, self.seed_limit, global_budget),
            candidate_limit=max(8, min(32, len(allowed) or 8)),
            max_depth=min(1, max_depth),
            beam_width=min(4, beam_width),
            max_nodes=global_budget,
            direction=direction,
            allowed_node_ids=allowed,
        )

        search = _merge_search_results(local, global_result, max_nodes=max_nodes)
        return RegionFirstSearchResult(search=search, route=route)

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
    ) -> RegionFirstSearchResult:
        route = self.index.route(concept, limit=self.region_limit)
        # Concept search is already global and lexically seeded. Keep that
        # proven path intact for S1; the region route is recorded for analysis
        # and becomes an optional accelerator rather than a hard filter.
        search = self.searcher.concept(
            concept,
            seed_limit=seed_limit,
            candidate_limit=candidate_limit,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        return RegionFirstSearchResult(search=search, route=route)
