"""Coverage and unknown-state reporting for behavioral evidence packets."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Mapping, Sequence, Set

from .behavior import BehaviorKind, BehaviorObservation
from .core import SemanticGraph


_BUILTIN_OR_INTRINSIC_CALLS = {
    "bool", "int", "float", "str", "len", "list", "dict", "set", "tuple",
    "min", "max", "sum", "sorted", "range", "enumerate", "zip", "print",
    "String", "Number", "Boolean", "trim", "toUpperCase", "toLowerCase",
    "replace", "split", "join", "map", "filter",
}


def behavior_coverage(
    graph: SemanticGraph,
    selected_symbol_ids: Sequence[str],
    candidates: Sequence[BehaviorObservation],
    delivered: Sequence[BehaviorObservation],
    *,
    unresolved_identifiers: Sequence[str] = (),
    omitted_relevant: int = 0,
    omitted_critical: int = 0,
) -> Mapping[str, Any]:
    """Summarize exactly what the local extractor did and did not establish.

    `local_source_scan_complete` means the supported extractor inspected the
    entire selected symbol source span.  It does *not* mean transitive runtime
    behavior, dynamic dispatch, or external effects are complete.
    """
    candidate_by_symbol = defaultdict(list)
    delivered_by_symbol = defaultdict(list)
    for item in candidates:
        candidate_by_symbol[item.symbol_id].append(item)
    for item in delivered:
        delivered_by_symbol[item.symbol_id].append(item)

    selected_names: Set[str] = set()
    for symbol_id in selected_symbol_ids:
        node = graph.node(symbol_id)
        if node is not None and node.name:
            selected_names.add(node.name)

    not_selected_calls = []
    for observation in candidates:
        if observation.kind not in {BehaviorKind.CALL, BehaviorKind.SIDE_EFFECT, BehaviorKind.TRANSFORM}:
            continue
        callee = str(observation.attributes.get("callee", "") or "")
        if not callee:
            continue
        tail = callee.rsplit(".", 1)[-1]
        if tail in _BUILTIN_OR_INTRINSIC_CALLS or tail in selected_names:
            continue
        not_selected_calls.append({
            "observation_id": observation.id,
            "symbol_id": observation.symbol_id,
            "callee": callee,
            "location": observation.location.to_dict(),
            "status": "callee_behavior_not_present_in_selected_symbols",
        })

    symbols = []
    for symbol_id in selected_symbol_ids:
        node = graph.node(symbol_id)
        if node is None or node.location is None:
            continue
        all_rows = candidate_by_symbol.get(symbol_id, [])
        sent_rows = delivered_by_symbol.get(symbol_id, [])
        candidate_counts = Counter(item.kind.value for item in all_rows)
        delivered_counts = Counter(item.kind.value for item in sent_rows)
        symbols.append({
            "symbol_id": symbol_id,
            "name": node.name,
            "source": node.location.to_dict(),
            "local_source_scan_complete": True,
            "candidate_behavior_kinds": dict(sorted(candidate_counts.items())),
            "delivered_behavior_kinds": dict(sorted(delivered_counts.items())),
            "candidate_observations": len(all_rows),
            "delivered_observations": len(sent_rows),
            "negative_evidence_scope": (
                "Absence means no explicit construct recognized by this extractor "
                "was found in the scanned local source span; it does not prove "
                "absence of transitive, dynamic, external, or runtime behavior."
            ),
        })

    unknowns = []
    if unresolved_identifiers:
        unknowns.append({
            "kind": "unresolved_requested_identifier",
            "values": sorted(set(str(value) for value in unresolved_identifiers)),
        })
    if omitted_critical:
        unknowns.append({
            "kind": "critical_behavior_omitted_by_budget",
            "count": int(omitted_critical),
        })
    if omitted_relevant:
        unknowns.append({
            "kind": "supporting_or_uncertain_behavior_omitted_by_budget",
            "count": int(omitted_relevant),
        })
    if not_selected_calls:
        unknowns.append({
            "kind": "callee_behavior_not_in_selected_symbols",
            "count": len(not_selected_calls),
        })

    return {
        "symbols": symbols,
        "unknowns": unknowns,
        "call_targets_without_selected_behavior": not_selected_calls,
        "claims": {
            "local_source_scan": "complete_for_supported_extractors",
            "transitive_runtime_behavior": "not_claimed_complete",
            "dynamic_dispatch": "unknown_unless_separately_evidenced",
            "external_side_effects": "unknown_unless_separately_evidenced",
            "unknown_is_not_false": True,
        },
    }
