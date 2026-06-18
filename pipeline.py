"""Compatibility pipeline for corrected FeynMap analysis behavior."""

from typing import Any, Dict, Set

try:
    from . import main as legacy_main
    from .impact_analysis import predict_change_impact
    from .reachability import analyze_reachability, possibly_unreachable_nodes, save_reachability
    from .trace_paths import generate_branch_preserving_ledger
except ImportError:
    import main as legacy_main
    from impact_analysis import predict_change_impact
    from reachability import analyze_reachability, possibly_unreachable_nodes, save_reachability
    from trace_paths import generate_branch_preserving_ledger


def detect_unused_nodes(enhanced_ledger: Dict[str, Any], graph_data: Dict[str, Any]) -> Set[str]:
    del enhanced_ledger
    report = analyze_reachability(graph_data)
    save_reachability(report)
    return possibly_unreachable_nodes(report)


def generate_node_ledger(
    node: Dict[str, Any],
    cache: Any,
    interaction_type: str,
    max_depth: int = legacy_main.DEFAULT_TRACE_DEPTH,
):
    return generate_branch_preserving_ledger(node, cache, interaction_type, max_depth)


legacy_main.detect_unused_nodes = detect_unused_nodes
legacy_main.generate_node_ledger = generate_node_ledger
legacy_main.predict_change_impact = predict_change_impact
run_feynmap = legacy_main.run_feynmap

__all__ = [
    "detect_unused_nodes",
    "generate_node_ledger",
    "predict_change_impact",
    "run_feynmap",
]
