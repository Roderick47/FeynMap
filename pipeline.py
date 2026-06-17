"""Compatibility pipeline that replaces legacy ghost detection with reachability."""

from typing import Any, Dict, Set

try:
    from . import main as legacy_main
    from .reachability import (
        analyze_reachability,
        possibly_unreachable_nodes,
        save_reachability,
    )
except ImportError:
    import main as legacy_main
    from reachability import (
        analyze_reachability,
        possibly_unreachable_nodes,
        save_reachability,
    )


def detect_unused_nodes(
    enhanced_ledger: Dict[str, Any], graph_data: Dict[str, Any]
) -> Set[str]:
    """Return only high-confidence candidates from evidence-based reachability.

    ``enhanced_ledger`` is accepted for backward compatibility but deliberately
    ignored. Presentation traces are not valid evidence that code is unused.
    """
    del enhanced_ledger
    report = analyze_reachability(graph_data)
    save_reachability(report)
    return possibly_unreachable_nodes(report)


# The legacy runner resolves this function from its own module globals. Replacing
# it here lets existing orchestration and output files continue working while the
# conceptual dead-code model is corrected.
legacy_main.detect_unused_nodes = detect_unused_nodes
run_feynmap = legacy_main.run_feynmap

__all__ = ["detect_unused_nodes", "run_feynmap"]
