"""Optional loader for the native FeynMap routing extension.

S6.5.2 only proves that the compiled PyO3 module can be discovered and that its
internal ABI matches Python. Routing behavior is introduced later.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Optional

from .rust_routing_boundary import RUST_ROUTING_BOUNDARY_VERSION


_NATIVE_MODULE_NAME = "_feynmap_native_routing"


def _load_native_module():
    try:
        return import_module(_NATIVE_MODULE_NAME)
    except ImportError:
        return None


def native_routing_available() -> bool:
    module = _load_native_module()
    if module is None:
        return False
    try:
        return str(module.abi_version()) == RUST_ROUTING_BOUNDARY_VERSION
    except (AttributeError, TypeError, ValueError):
        return False


def native_routing_info() -> Dict[str, Optional[Any]]:
    module = _load_native_module()
    if module is None:
        return {
            "available": False,
            "module": _NATIVE_MODULE_NAME,
            "expected_abi_version": RUST_ROUTING_BOUNDARY_VERSION,
            "abi_version": None,
            "implementation": None,
        }

    abi_version = str(module.abi_version())
    implementation = str(module.implementation())
    return {
        "available": abi_version == RUST_ROUTING_BOUNDARY_VERSION,
        "module": _NATIVE_MODULE_NAME,
        "expected_abi_version": RUST_ROUTING_BOUNDARY_VERSION,
        "abi_version": abi_version,
        "implementation": implementation,
    }
