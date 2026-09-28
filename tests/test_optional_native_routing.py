"""S6.9 optional native routing: opt-in, lazy reuse, verification and fallback.

The fake native module runs the compact Python reference so the mode-switch
contract is tested in ordinary Python CI without requiring a Rust wheel.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from feynmap.core import NodeKind, SemanticGraph, SemanticNode, SourceLocation
from feynmap.routing import RegionIndex
from feynmap.rust_routing_boundary import (
    RUST_ROUTING_BOUNDARY_VERSION,
    RoutingKernelRequest,
    prepare_region_routing_index,
    route_compact_python_reference,
)


def _graph():
    return SemanticGraph(
        nodes=[
            SemanticNode(
                id="n0", name="match alpha", kind=NodeKind.FUNCTION,
                qualified_name="pkg.a.alpha",
                location=SourceLocation(path="alpha.py", line=1),
            ),
            SemanticNode(
                id="n1", name="match beta", kind=NodeKind.FUNCTION,
                qualified_name="pkg.b.beta",
                location=SourceLocation(path="beta.py", line=1),
            ),
        ]
    )


def _fake_native(monkeypatch, index, *, break_route=False, mismatch=False):
    from feynmap import native_routing

    reference = prepare_region_routing_index(index)
    calls = {"construct": 0, "route": 0}

    class FakeNativeIndex:
        def __init__(self, *arguments):
            calls["construct"] += 1
            assert len(arguments) == 9

        def route(self, *arguments):
            calls["route"] += 1
            if break_route:
                raise RuntimeError("intentional native failure")
            result = route_compact_python_reference(
                reference.kernel,
                RoutingKernelRequest(*arguments),
            )
            if mismatch:
                return result.candidate_regions, (0,), (42.0,)
            return (
                result.candidate_regions,
                result.selected_region_indices,
                result.selected_scores,
            )

    module = SimpleNamespace(
        abi_version=lambda: RUST_ROUTING_BOUNDARY_VERSION,
        NativeRegionIndex=FakeNativeIndex,
    )
    monkeypatch.setattr(native_routing, "_load_native_module", lambda: module)
    return calls


def _same_route(index, query, **kwargs):
    original = index._route_python(query, **kwargs)
    routed = index.route(query, **kwargs)
    assert routed.selected_regions == original.selected_regions
    assert routed.candidate_regions == original.candidate_regions
    assert routed.anchor_region == original.anchor_region
    assert set(routed.scores) == set(original.scores)
    for region_id in original.scores:
        assert routed.scores[region_id] == pytest.approx(
            original.scores[region_id], rel=1e-12, abs=1e-12,
        )


def test_python_remains_the_default_even_with_fake_native_available(monkeypatch):
    monkeypatch.delenv("FEYNMAP_NATIVE_ROUTING", raising=False)
    index = RegionIndex(_graph())
    assert index.native_routing_stats["status"] == "disabled"
    _same_route(index, "match alpha", anchor_node_id="n0")
    assert index.native_routing_stats["setup_attempts"] == 0


def test_opt_in_lazily_builds_exactly_one_reusable_native_index(monkeypatch):
    index = RegionIndex(_graph(), native_routing=True)
    calls = _fake_native(monkeypatch, index)
    assert index.native_routing_stats["status"] == "pending"
    assert index.native_routing_stats["setup_attempts"] == 0

    for query in ("match alpha", "match beta", "unknown thing", ""):
        _same_route(index, query, anchor_node_id="n0")
    assert calls == {"construct": 1, "route": 4}
    assert index.native_routing_stats["status"] == "ready"
    assert index.native_routing_stats["native_route_calls"] == 4
    assert index.native_routing_stats["fallbacks"] == 0


def test_environment_is_opt_in_and_explicit_false_overrides_it(monkeypatch):
    monkeypatch.setenv("FEYNMAP_NATIVE_ROUTING", "true")
    index = RegionIndex(_graph())
    assert index.native_routing_stats["requested"] is True
    disabled = RegionIndex(_graph(), native_routing=False)
    assert disabled.native_routing_stats["status"] == "disabled"


def test_unavailable_native_wheel_falls_back_once_without_retries(monkeypatch):
    from feynmap import native_routing

    calls = {"loads": 0}

    def absent():
        calls["loads"] += 1
        return None

    monkeypatch.setattr(native_routing, "_load_native_module", absent)
    index = RegionIndex(_graph(), native_routing=True)
    for _ in range(3):
        _same_route(index, "alpha", anchor_node_id="n0")
    assert index.native_routing_stats["status"] == "fallback"
    assert index.native_routing_stats["failure_reason"] == "setup:ImportError"
    assert index.native_routing_stats["fallbacks"] == 1
    assert index.native_routing_stats["setup_attempts"] == 1
    assert calls["loads"] == 1


def test_wrong_abi_is_not_used_and_python_remains_available(monkeypatch):
    from feynmap import native_routing

    wrong = SimpleNamespace(
        abi_version=lambda: "99.0.0",
        NativeRegionIndex=lambda *args: pytest.fail("wrong ABI was constructed"),
    )
    monkeypatch.setattr(native_routing, "_load_native_module", lambda: wrong)
    index = RegionIndex(_graph(), native_routing=True)
    _same_route(index, "alpha")
    assert index.native_routing_stats["status"] == "fallback"
    assert index.native_routing_stats["failure_reason"] == "setup:ValueError"


def test_runtime_native_failure_disables_native_for_rest_of_index(monkeypatch):
    index = RegionIndex(_graph(), native_routing=True)
    calls = _fake_native(monkeypatch, index, break_route=True)
    _same_route(index, "alpha")
    _same_route(index, "beta")
    assert calls == {"construct": 1, "route": 1}
    assert index.native_routing_stats["status"] == "fallback"
    assert index.native_routing_stats["failure_reason"] == "route:RuntimeError"
    assert index.native_routing_stats["fallbacks"] == 1


def test_diagnostic_shadow_verify_rejects_syntactically_valid_wrong_output(monkeypatch):
    monkeypatch.setenv("FEYNMAP_NATIVE_ROUTING_VERIFY", "1")
    index = RegionIndex(_graph(), native_routing=True)
    _fake_native(monkeypatch, index, mismatch=True)
    _same_route(index, "match beta", anchor_node_id="n1")
    assert index.native_routing_stats["status"] == "fallback"
    assert index.native_routing_stats["failure_reason"] == "route:ValueError"


def test_one_time_native_setup_is_serialized_across_parallel_routes(monkeypatch):
    index = RegionIndex(_graph(), native_routing=True)
    calls = _fake_native(monkeypatch, index)
    with ThreadPoolExecutor(max_workers=5) as executor:
        routes = list(executor.map(lambda _: index.route("alpha"), range(10)))
    assert all(route.selected_regions == routes[0].selected_regions for route in routes)
    assert calls["construct"] == 1
    assert index.native_routing_stats["setup_attempts"] == 1
    assert index.native_routing_stats["native_route_calls"] == 10
