"""Python reference for the S6.5.1 Python↔Rust routing boundary.

This module defines the compact numeric representation that a future PyO3
NativeRegionIndex will own. It deliberately contains no Rust implementation.
The pure-Python compact kernel is a differential reference for the future
native implementation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Set, Tuple

from .routing import RegionIndex, RegionRouteResult, _region_weight, _tokens


RUST_ROUTING_BOUNDARY_SCHEMA = "feynmap.native_region_routing"
RUST_ROUTING_BOUNDARY_VERSION = "1.0.0"


@dataclass(frozen=True)
class RoutingKernelData:
    """Static numeric arrays copied into the future Rust-owned index once."""

    region_count: int
    region_weights: Tuple[float, ...]
    idf_by_token: Tuple[float, ...]
    unknown_token_idf: float
    region_term_offsets: Tuple[int, ...]
    region_term_ids: Tuple[int, ...]
    path_term_offsets: Tuple[int, ...]
    path_term_ids: Tuple[int, ...]
    adjacency_offsets: Tuple[int, ...]
    adjacency_region_indices: Tuple[int, ...]

    def validate(self) -> None:
        if self.region_count < 0:
            raise ValueError("region_count must be non-negative")
        if len(self.region_weights) != self.region_count:
            raise ValueError("region_weights length must equal region_count")
        expected_offsets = self.region_count + 1
        for name, offsets, values in (
            ("region terms", self.region_term_offsets, self.region_term_ids),
            ("path terms", self.path_term_offsets, self.path_term_ids),
            ("adjacency", self.adjacency_offsets, self.adjacency_region_indices),
        ):
            if len(offsets) != expected_offsets:
                raise ValueError("%s offsets must have region_count + 1 entries" % name)
            if offsets and offsets[0] != 0:
                raise ValueError("%s offsets must start at zero" % name)
            if any(left > right for left, right in zip(offsets, offsets[1:])):
                raise ValueError("%s offsets must be monotonic" % name)
            if offsets and offsets[-1] != len(values):
                raise ValueError("%s final offset must equal value count" % name)
        token_count = len(self.idf_by_token)
        if any(token_id < 0 or token_id >= token_count for token_id in self.region_term_ids):
            raise ValueError("region term id outside vocabulary")
        if any(token_id < 0 or token_id >= token_count for token_id in self.path_term_ids):
            raise ValueError("path term id outside vocabulary")
        if any(
            region_id < 0 or region_id >= self.region_count
            for region_id in self.adjacency_region_indices
        ):
            raise ValueError("adjacency region index outside region table")


@dataclass(frozen=True)
class PreparedRegionRoutingIndex:
    """Python-owned names/maps plus static data intended for Rust ownership."""

    schema: str
    schema_version: str
    region_ids: Tuple[str, ...]
    region_index_by_id: Mapping[str, int]
    token_to_id: Mapping[str, int]
    kernel: RoutingKernelData

    def validate(self) -> None:
        if self.schema != RUST_ROUTING_BOUNDARY_SCHEMA:
            raise ValueError("unsupported Rust routing boundary schema")
        if self.schema_version != RUST_ROUTING_BOUNDARY_VERSION:
            raise ValueError("unsupported Rust routing boundary version")
        if len(self.region_ids) != self.kernel.region_count:
            raise ValueError("region id table must match kernel region count")
        if tuple(sorted(self.region_ids)) != self.region_ids:
            raise ValueError("region ids must be lexically sorted")
        for index, region_id in enumerate(self.region_ids):
            if self.region_index_by_id.get(region_id) != index:
                raise ValueError("region index map does not match region id table")
        self.kernel.validate()


@dataclass(frozen=True)
class RoutingKernelRequest:
    """Small per-query request intended to cross Python→Rust."""

    query_term_ids: Tuple[int, ...]
    unknown_query_term_count: int
    anchor_region_index: Optional[int]
    limit: int

    @property
    def has_query_terms(self) -> bool:
        return bool(self.query_term_ids or self.unknown_query_term_count)

    def validate(self, kernel: RoutingKernelData) -> None:
        if self.unknown_query_term_count < 0:
            raise ValueError("unknown_query_term_count must be non-negative")
        if (
            self.anchor_region_index is not None
            and (
                self.anchor_region_index < 0
                or self.anchor_region_index >= kernel.region_count
            )
        ):
            raise ValueError("anchor_region_index outside region table")
        if self.limit < 1:
            raise ValueError("limit must be positive")
        if tuple(sorted(set(self.query_term_ids))) != self.query_term_ids:
            raise ValueError("query term ids must be sorted and unique")
        if any(
            token_id < 0 or token_id >= len(kernel.idf_by_token)
            for token_id in self.query_term_ids
        ):
            raise ValueError("query term id outside vocabulary")


@dataclass(frozen=True)
class RoutingKernelResponse:
    """Small native→Python response using numeric region indexes only."""

    candidate_regions: int
    selected_region_indices: Tuple[int, ...]
    selected_scores: Tuple[float, ...]

    def validate(self, kernel: RoutingKernelData) -> None:
        if self.candidate_regions < 0:
            raise ValueError("candidate_regions must be non-negative")
        if len(self.selected_region_indices) != len(self.selected_scores):
            raise ValueError("selected indexes and scores must align")
        if len(set(self.selected_region_indices)) != len(self.selected_region_indices):
            raise ValueError("selected region indexes must be unique")
        if any(
            region_id < 0 or region_id >= kernel.region_count
            for region_id in self.selected_region_indices
        ):
            raise ValueError("selected region index outside region table")


def _csr_rows(rows: Sequence[Sequence[int]]) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    offsets = [0]
    values = []
    for row in rows:
        values.extend(row)
        offsets.append(len(values))
    return tuple(offsets), tuple(values)


def prepare_region_routing_index(index: RegionIndex) -> PreparedRegionRoutingIndex:
    """Convert RegionIndex into a deterministic numeric FFI representation."""

    region_ids = tuple(sorted(index.regions))
    region_index_by_id: Dict[str, int] = {
        region_id: position
        for position, region_id in enumerate(region_ids)
    }

    vocabulary: Set[str] = set()
    for region_id in region_ids:
        vocabulary.update(index.regions[region_id].terms)
        vocabulary.update(_tokens(region_id))
    terms = tuple(sorted(vocabulary))
    token_to_id: Dict[str, int] = {
        token: position
        for position, token in enumerate(terms)
    }

    idf_by_token = tuple(index._idf(token) for token in terms)
    unknown_token_idf = math.log((len(index.regions) + 1.0) / 1.0) + 1.0

    region_term_rows = []
    path_term_rows = []
    adjacency_rows = []
    region_weights = []
    for region_id in region_ids:
        region = index.regions[region_id]
        region_term_rows.append(
            tuple(sorted(token_to_id[token] for token in region.terms))
        )
        path_term_rows.append(
            tuple(sorted(token_to_id[token] for token in set(_tokens(region_id))))
        )
        adjacency_rows.append(
            tuple(
                sorted(
                    region_index_by_id[neighbor]
                    for neighbor in index.adjacency.get(region_id, set())
                    if neighbor in region_index_by_id
                )
            )
        )
        region_weights.append(_region_weight(region_id))

    region_term_offsets, region_term_ids = _csr_rows(region_term_rows)
    path_term_offsets, path_term_ids = _csr_rows(path_term_rows)
    adjacency_offsets, adjacency_region_indices = _csr_rows(adjacency_rows)

    prepared = PreparedRegionRoutingIndex(
        schema=RUST_ROUTING_BOUNDARY_SCHEMA,
        schema_version=RUST_ROUTING_BOUNDARY_VERSION,
        region_ids=region_ids,
        region_index_by_id=region_index_by_id,
        token_to_id=token_to_id,
        kernel=RoutingKernelData(
            region_count=len(region_ids),
            region_weights=tuple(region_weights),
            idf_by_token=idf_by_token,
            unknown_token_idf=unknown_token_idf,
            region_term_offsets=region_term_offsets,
            region_term_ids=region_term_ids,
            path_term_offsets=path_term_offsets,
            path_term_ids=path_term_ids,
            adjacency_offsets=adjacency_offsets,
            adjacency_region_indices=adjacency_region_indices,
        ),
    )
    prepared.validate()
    return prepared


def prepare_routing_request(
    prepared: PreparedRegionRoutingIndex,
    query: str,
    *,
    anchor_region: Optional[str],
    limit: int,
) -> RoutingKernelRequest:
    """Tokenize in Python, then map the query to compact numeric IDs."""

    query_tokens = set(_tokens(query))
    known = tuple(
        sorted(
            prepared.token_to_id[token]
            for token in query_tokens
            if token in prepared.token_to_id
        )
    )
    unknown_count = sum(
        1
        for token in query_tokens
        if token not in prepared.token_to_id
    )
    anchor_index = (
        prepared.region_index_by_id.get(anchor_region)
        if anchor_region is not None
        else None
    )
    request = RoutingKernelRequest(
        query_term_ids=known,
        unknown_query_term_count=unknown_count,
        anchor_region_index=anchor_index,
        limit=max(1, int(limit)),
    )
    request.validate(prepared.kernel)
    return request


def _row(
    offsets: Tuple[int, ...],
    values: Tuple[int, ...],
    index: int,
) -> Tuple[int, ...]:
    return values[offsets[index]:offsets[index + 1]]


def _weighted_intersection(
    query_ids: Tuple[int, ...],
    row_ids: Tuple[int, ...],
    idf_by_token: Tuple[float, ...],
) -> float:
    """Two-pointer overlap over sorted integer IDs; directly portable to Rust."""

    total = 0.0
    left = 0
    right = 0
    while left < len(query_ids) and right < len(row_ids):
        query_id = query_ids[left]
        row_id = row_ids[right]
        if query_id == row_id:
            total += idf_by_token[query_id]
            left += 1
            right += 1
        elif query_id < row_id:
            left += 1
        else:
            right += 1
    return total


def route_compact_python_reference(
    kernel: RoutingKernelData,
    request: RoutingKernelRequest,
) -> RoutingKernelResponse:
    """Reference kernel over only data that the Rust object will own."""

    kernel.validate()
    request.validate(kernel)

    query_ids = request.query_term_ids
    denominator = 1.0
    if request.has_query_terms:
        denominator = sum(kernel.idf_by_token[token_id] for token_id in query_ids)
        denominator += (
            float(request.unknown_query_term_count)
            * kernel.unknown_token_idf
        )

    anchor = request.anchor_region_index
    neighbor_regions = set()
    if anchor is not None:
        neighbor_regions.update(
            _row(
                kernel.adjacency_offsets,
                kernel.adjacency_region_indices,
                anchor,
            )
        )

    scored = []
    direct_path_scored = []
    considered = 0
    score_by_region: Dict[int, float] = {}

    for region_index in range(kernel.region_count):
        weight = kernel.region_weights[region_index]
        if weight < 0.2 and region_index != anchor:
            continue
        considered += 1

        lexical = _weighted_intersection(
            query_ids,
            _row(
                kernel.region_term_offsets,
                kernel.region_term_ids,
                region_index,
            ),
            kernel.idf_by_token,
        )
        path_match = _weighted_intersection(
            query_ids,
            _row(
                kernel.path_term_offsets,
                kernel.path_term_ids,
                region_index,
            ),
            kernel.idf_by_token,
        )
        if request.has_query_terms:
            lexical /= denominator
            path_match /= denominator

        lexical = (lexical + (1.5 * path_match)) * weight
        locality = 0.0
        if region_index == anchor:
            locality = 2.0
        elif region_index in neighbor_regions:
            locality = 0.10
        score = lexical + locality

        if score > 0.0:
            scored.append((score, region_index))
            score_by_region[region_index] = score
        if path_match > 0.0:
            direct_path_scored.append((path_match * weight, region_index))

    scored.sort(key=lambda item: (-item[0], item[1]))
    direct_path_scored.sort(key=lambda item: (-item[0], item[1]))

    selected = []
    seen = set()
    general_index = 0
    path_index = 0
    limit = request.limit
    while len(selected) < limit and (
        general_index < len(scored)
        or path_index < len(direct_path_scored)
    ):
        if general_index < len(scored):
            region_index = scored[general_index][1]
            general_index += 1
            if region_index not in seen:
                selected.append(region_index)
                seen.add(region_index)
                if len(selected) >= limit:
                    break
        if path_index < len(direct_path_scored):
            region_index = direct_path_scored[path_index][1]
            path_index += 1
            if region_index not in seen:
                selected.append(region_index)
                seen.add(region_index)

    if anchor is not None and anchor not in selected:
        selected.insert(0, anchor)
        selected = selected[:limit]

    if not selected and anchor is not None:
        selected = [anchor]

    selected_scores = []
    for region_index in selected:
        if region_index in score_by_region:
            selected_scores.append(score_by_region[region_index])
        elif region_index == anchor:
            selected_scores.append(2.0)
        else:
            selected_scores.append(0.0)

    response = RoutingKernelResponse(
        candidate_regions=considered,
        selected_region_indices=tuple(selected),
        selected_scores=tuple(selected_scores),
    )
    response.validate(kernel)
    return response


def materialize_region_route(
    prepared: PreparedRegionRoutingIndex,
    query: str,
    *,
    anchor_region: Optional[str],
    response: RoutingKernelResponse,
) -> RegionRouteResult:
    response.validate(prepared.kernel)
    selected_regions = tuple(
        prepared.region_ids[index]
        for index in response.selected_region_indices
    )
    scores = {
        prepared.region_ids[index]: float(score)
        for index, score in zip(
            response.selected_region_indices,
            response.selected_scores,
        )
    }
    return RegionRouteResult(
        query=str(query),
        anchor_region=anchor_region,
        candidate_regions=response.candidate_regions,
        selected_regions=selected_regions,
        scores=scores,
    )


def route_through_compact_python_boundary(
    index: RegionIndex,
    prepared: PreparedRegionRoutingIndex,
    query: str,
    *,
    anchor_node_id: Optional[str] = None,
    limit: int = 8,
) -> RegionRouteResult:
    """End-to-end Python reference for the future PyO3 call path."""

    anchor_region = (
        index.region_for_node(anchor_node_id)
        if anchor_node_id
        else None
    )
    request = prepare_routing_request(
        prepared,
        query,
        anchor_region=anchor_region,
        limit=limit,
    )
    response = route_compact_python_reference(prepared.kernel, request)
    return materialize_region_route(
        prepared,
        query,
        anchor_region=anchor_region,
        response=response,
    )
