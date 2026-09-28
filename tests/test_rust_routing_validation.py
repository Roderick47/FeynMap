"""S6.7 Python-side validation of the native ABI acceptance domain."""
from dataclasses import replace
import math

import pytest

from feynmap.rust_routing_boundary import (
    MAX_NATIVE_U32, RoutingKernelData, RoutingKernelRequest,
)


def _good_kernel():
    return RoutingKernelData(
        region_count=2,
        region_weights=(1.0, 1.0),
        idf_by_token=(1.0, 2.0, 3.0),
        unknown_token_idf=4.0,
        region_term_offsets=(0, 2, 3),
        region_term_ids=(0, 1, 2),
        path_term_offsets=(0, 1, 2),
        path_term_ids=(0, 2),
        adjacency_offsets=(0, 1, 2),
        adjacency_region_indices=(1, 0),
    )


@pytest.mark.parametrize(
    "changed,match",
    [
        ({"region_weights": (-1.0, 1.0)}, "finite and non-negative"),
        ({"region_weights": (float("nan"), 1.0)}, "finite and non-negative"),
        ({"idf_by_token": (1.0, 0.0, 3.0)}, "finite and positive"),
        ({"unknown_token_idf": float("inf")}, "finite and positive"),
        ({"region_term_offsets": (1, 2, 3)}, "start at zero"),
        ({"region_term_offsets": (0, 3, 2)}, "monotonic"),
        ({"region_term_offsets": (0, 2, 4)}, "final offset"),
        ({"region_term_ids": (0, 0, 2)}, "sorted and unique"),
        ({"path_term_ids": (3, 2)}, "outside vocabulary"),
        ({"adjacency_region_indices": (2, 0)}, "outside region table"),
        ({"region_term_offsets": (0, MAX_NATIVE_U32 + 1, 3)}, "monotonic"),
    ],
)
def test_python_boundary_rejects_malformed_native_arrays(changed, match):
    with pytest.raises(ValueError, match=match):
        replace(_good_kernel(), **changed).validate()


@pytest.mark.parametrize(
    "changed,match",
    [
        ({"query_term_ids": (0, 0)}, "sorted and unique"),
        ({"query_term_ids": (3,)}, "outside vocabulary"),
        ({"unknown_query_term_count": -1}, "u32 range"),
        ({"unknown_query_term_count": MAX_NATIVE_U32 + 1}, "u32 range"),
        ({"anchor_region_index": 2}, "outside region table"),
        ({"limit": 0}, "positive u32 range"),
        ({"limit": MAX_NATIVE_U32 + 1}, "positive u32 range"),
    ],
)
def test_python_boundary_rejects_invalid_native_requests(changed, match):
    request = RoutingKernelRequest(
        query_term_ids=(0,),
        unknown_query_term_count=0,
        anchor_region_index=None,
        limit=2,
    )
    with pytest.raises(ValueError, match=match):
        replace(request, **changed).validate(_good_kernel())


def test_valid_empty_kernel_is_an_accepted_native_boundary():
    empty = RoutingKernelData(
        region_count=0,
        region_weights=(),
        idf_by_token=(),
        unknown_token_idf=1.0,
        region_term_offsets=(0,),
        region_term_ids=(),
        path_term_offsets=(0,),
        path_term_ids=(),
        adjacency_offsets=(0,),
        adjacency_region_indices=(),
    )
    empty.validate()
    RoutingKernelRequest((), 1, None, 1).validate(empty)
