from feynmap.native_routing import (
    native_routing_available,
    native_routing_info,
)
from feynmap.rust_routing_boundary import RUST_ROUTING_BOUNDARY_VERSION


def test_native_loader_is_safe_when_extension_is_optional():
    info = native_routing_info()

    assert info["module"] == "_feynmap_native_routing"
    assert info["expected_abi_version"] == RUST_ROUTING_BOUNDARY_VERSION
    assert native_routing_available() is bool(info["available"])
    if info["available"]:
        assert info["abi_version"] == RUST_ROUTING_BOUNDARY_VERSION
        assert info["implementation"] == "rust-pyo3"
    else:
        assert info["abi_version"] is None
        assert info["implementation"] is None
