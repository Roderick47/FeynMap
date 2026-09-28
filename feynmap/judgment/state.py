"""Deterministic state shaping for external judgment providers."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Union


def _task_payload(task: Union[str, Mapping[str, Any]]) -> Dict[str, Any]:
    if isinstance(task, str):
        if not task.strip():
            raise ValueError("task description must not be empty")
        return {"description": task}
    if not isinstance(task, Mapping) or not task:
        raise ValueError("task must be a non-empty string or mapping")
    return dict(task)


def build_judgment_state(
    task: Union[str, Mapping[str, Any]],
    context_bundle: Mapping[str, Any],
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build compact provider-neutral state from a grounded context bundle.

    This function intentionally preserves FeynMap evidence labels as evidence
    metadata. It does not reinterpret detector confidence as probability and it
    does not add provider-specific fields.
    """
    if not isinstance(context_bundle, Mapping):
        raise ValueError("context_bundle must be a mapping")
    root = context_bundle.get("root")
    if not isinstance(root, Mapping):
        raise ValueError("context_bundle must include a grounded root")

    candidates = context_bundle.get("nodes") or []
    relationships = context_bundle.get("relationships") or []
    if not isinstance(candidates, list) or not isinstance(relationships, list):
        raise ValueError("context_bundle nodes and relationships must be lists")

    budget = context_bundle.get("budget") or {}
    omissions = {}
    if isinstance(budget, Mapping):
        for key in (
            "omitted_nodes",
            "omitted_relationships",
            "truncated",
            "estimated_tokens",
        ):
            if key in budget:
                omissions[key] = budget[key]

    snapshot = context_bundle.get("snapshot") or {}
    grounding = context_bundle.get("grounding") or {}
    state: Dict[str, Any] = {
        "task": _task_payload(task),
        "snapshot": dict(snapshot) if isinstance(snapshot, Mapping) else snapshot,
        "root": dict(root),
        "candidates": [dict(item) if isinstance(item, Mapping) else item for item in candidates],
        "relationships": [dict(item) if isinstance(item, Mapping) else item for item in relationships],
        "grounding": dict(grounding) if isinstance(grounding, Mapping) else grounding,
        "omissions": omissions,
    }
    if extra:
        state["extra"] = dict(extra)
    return state
