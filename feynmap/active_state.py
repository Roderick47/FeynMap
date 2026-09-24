"""S4 active working state for long-horizon agents.

The canonical SemanticGraph (and immutable repository snapshot) remains the source
of truth. ActiveState deliberately stores only stable references plus bounded
task memory. Exact nodes/relationships are rehydrated from the graph on demand,
so a long-running agent does not accumulate a second, stale copy of repository
knowledge in conversation state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .context import estimate_tokens
from .context_pipeline import SparseContextPipeline, SparseContextResult
from .core import SemanticEdge, SemanticGraph
from .judgment.contracts import JudgmentProvider
from .minimal_context import MinimalContextBudget


ACTIVE_STATE_SCHEMA = "feynmap.active_state"
ACTIVE_STATE_SCHEMA_VERSION = "1.0.0"


def _dedupe(values: Iterable[str], limit: Optional[int] = None) -> Tuple[str, ...]:
    result: List[str] = []
    seen: Set[str] = set()
    for raw in values:
        value = str(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if limit is not None and len(result) >= limit:
            break
    return tuple(result)


def _terms(value: str) -> Tuple[str, ...]:
    cleaned = "".join(
        character.casefold() if character.isalnum() else " "
        for character in str(value or "")
    )
    return _dedupe(
        token for token in cleaned.split()
        if len(token) >= 3
    )


@dataclass(frozen=True)
class ActiveStateBudget:
    """Bound the task-local state independently of the persistent graph."""

    max_nodes: int = 32
    max_edges: int = 48
    max_regions: int = 8
    max_retrievals: int = 8
    max_open_questions: int = 8
    max_contradictions: int = 8
    max_concepts: int = 32

    def normalized(self) -> "ActiveStateBudget":
        return ActiveStateBudget(
            max_nodes=max(1, int(self.max_nodes)),
            max_edges=max(0, int(self.max_edges)),
            max_regions=max(1, int(self.max_regions)),
            max_retrievals=max(1, int(self.max_retrievals)),
            max_open_questions=max(1, int(self.max_open_questions)),
            max_contradictions=max(1, int(self.max_contradictions)),
            max_concepts=max(1, int(self.max_concepts)),
        )


@dataclass(frozen=True)
class ActiveRetrieval:
    query: str
    root_node_id: str
    stage: str
    effort: str
    region_ids: Tuple[str, ...]
    node_ids: Tuple[str, ...]
    edge_ids: Tuple[str, ...]
    delivered_tokens: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "root_node_id": self.root_node_id,
            "stage": self.stage,
            "effort": self.effort,
            "region_ids": list(self.region_ids),
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "delivered_tokens": int(self.delivered_tokens),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ActiveRetrieval":
        return cls(
            query=str(payload.get("query", "")),
            root_node_id=str(payload.get("root_node_id", "")),
            stage=str(payload.get("stage", "")),
            effort=str(payload.get("effort", "")),
            region_ids=tuple(str(item) for item in payload.get("region_ids", []) or []),
            node_ids=tuple(str(item) for item in payload.get("node_ids", []) or []),
            edge_ids=tuple(str(item) for item in payload.get("edge_ids", []) or []),
            delivered_tokens=int(payload.get("delivered_tokens", 0)),
        )


@dataclass(frozen=True)
class ActiveState:
    """Portable task state containing graph references, not graph copies."""

    snapshot_id: str
    task: str
    step: int
    focus_node_ids: Tuple[str, ...]
    active_node_ids: Tuple[str, ...]
    active_edge_ids: Tuple[str, ...]
    active_region_ids: Tuple[str, ...]
    concepts: Tuple[str, ...] = ()
    open_questions: Tuple[str, ...] = ()
    contradictions: Tuple[str, ...] = ()
    retrievals: Tuple[ActiveRetrieval, ...] = ()
    invalidated: bool = False
    invalidation_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": ACTIVE_STATE_SCHEMA,
            "schema_version": ACTIVE_STATE_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "task": self.task,
            "step": int(self.step),
            "focus_node_ids": list(self.focus_node_ids),
            "active_node_ids": list(self.active_node_ids),
            "active_edge_ids": list(self.active_edge_ids),
            "active_region_ids": list(self.active_region_ids),
            "concepts": list(self.concepts),
            "open_questions": list(self.open_questions),
            "contradictions": list(self.contradictions),
            "retrievals": [item.to_dict() for item in self.retrievals],
            "invalidated": bool(self.invalidated),
            "invalidation_reason": self.invalidation_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ActiveState":
        schema = payload.get("schema")
        if schema and schema != ACTIVE_STATE_SCHEMA:
            raise ValueError("unsupported active-state schema: %s" % schema)
        version = payload.get("schema_version")
        if version and version != ACTIVE_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported active-state schema version: %s" % version)
        return cls(
            snapshot_id=str(payload.get("snapshot_id", "")),
            task=str(payload.get("task", "")),
            step=int(payload.get("step", 0)),
            focus_node_ids=tuple(str(item) for item in payload.get("focus_node_ids", []) or []),
            active_node_ids=tuple(str(item) for item in payload.get("active_node_ids", []) or []),
            active_edge_ids=tuple(str(item) for item in payload.get("active_edge_ids", []) or []),
            active_region_ids=tuple(str(item) for item in payload.get("active_region_ids", []) or []),
            concepts=tuple(str(item) for item in payload.get("concepts", []) or []),
            open_questions=tuple(str(item) for item in payload.get("open_questions", []) or []),
            contradictions=tuple(str(item) for item in payload.get("contradictions", []) or []),
            retrievals=tuple(
                ActiveRetrieval.from_dict(item)
                for item in payload.get("retrievals", []) or []
                if isinstance(item, Mapping)
            ),
            invalidated=bool(payload.get("invalidated", False)),
            invalidation_reason=(
                str(payload.get("invalidation_reason"))
                if payload.get("invalidation_reason") is not None
                else None
            ),
        )

    @property
    def cumulative_delivered_tokens(self) -> int:
        return sum(item.delivered_tokens for item in self.retrievals)

    @property
    def compact_tokens(self) -> int:
        return estimate_tokens(self.to_dict())


@dataclass(frozen=True)
class ActiveStateTransition:
    state: ActiveState
    retrieval: SparseContextResult
    reused_node_ids: Tuple[str, ...]
    introduced_node_ids: Tuple[str, ...]
    dropped_node_ids: Tuple[str, ...]
    working_context_tokens: int

    @property
    def context_growth_avoided_tokens(self) -> int:
        return max(
            0,
            self.state.cumulative_delivered_tokens - int(self.working_context_tokens),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "transition": {
                "reused_node_ids": list(self.reused_node_ids),
                "introduced_node_ids": list(self.introduced_node_ids),
                "dropped_node_ids": list(self.dropped_node_ids),
            },
            "metrics": {
                "compact_state_tokens": self.state.compact_tokens,
                "working_context_tokens": int(self.working_context_tokens),
                "cumulative_delivered_tokens": self.state.cumulative_delivered_tokens,
                "context_growth_avoided_tokens": self.context_growth_avoided_tokens,
            },
        }


class ActiveStateInvalidated(RuntimeError):
    """Raised when an active state no longer matches canonical graph evidence."""


class ActiveStateRuntime:
    """Maintain bounded task state over an immutable semantic snapshot."""

    def __init__(
        self,
        graph: SemanticGraph,
        snapshot_id: str,
        provider: Optional[JudgmentProvider] = None,
        *,
        region_limit: int = 8,
        region_seed_limit: int = 12,
        budget: Optional[ActiveStateBudget] = None,
    ) -> None:
        if not str(snapshot_id):
            raise ValueError("snapshot_id is required for active state")
        self.graph = graph
        self.snapshot_id = str(snapshot_id)
        self.budget = (budget or ActiveStateBudget()).normalized()
        self.pipeline = SparseContextPipeline(
            graph,
            provider=provider,
            region_limit=region_limit,
            region_seed_limit=region_seed_limit,
        )
        self.region_index = self.pipeline.search.index
        self._edge_by_id = {edge.id: edge for edge in graph.edges}

    def begin_from_node(
        self,
        node: str,
        goal: str,
        *,
        task: Optional[str] = None,
        open_questions: Sequence[str] = (),
        contradictions: Sequence[str] = (),
        context_budget: Optional[MinimalContextBudget] = None,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> ActiveStateTransition:
        retrieval = self.pipeline.from_node(
            node,
            goal,
            context_budget=context_budget,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        root = retrieval.activation.search.roots[0].id if retrieval.activation.search.roots else str(node)
        return self._transition(
            previous=None,
            retrieval=retrieval,
            root_node_id=root,
            goal=goal,
            task=task or goal,
            open_questions=open_questions,
            contradictions=contradictions,
        )

    def continue_from_node(
        self,
        state: ActiveState,
        node: str,
        goal: str,
        *,
        open_questions: Optional[Sequence[str]] = None,
        contradictions: Optional[Sequence[str]] = None,
        context_budget: Optional[MinimalContextBudget] = None,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> ActiveStateTransition:
        self._require_fresh(state)
        retrieval = self.pipeline.from_node(
            node,
            goal,
            context_budget=context_budget,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        root = retrieval.activation.search.roots[0].id if retrieval.activation.search.roots else str(node)
        return self._transition(
            previous=state,
            retrieval=retrieval,
            root_node_id=root,
            goal=goal,
            task=state.task,
            open_questions=state.open_questions if open_questions is None else open_questions,
            contradictions=state.contradictions if contradictions is None else contradictions,
        )

    def continue_from_focus(
        self,
        state: ActiveState,
        goal: str,
        **kwargs: Any
    ) -> ActiveStateTransition:
        self._require_fresh(state)
        if not state.focus_node_ids:
            raise ValueError("active state has no focus node")
        return self.continue_from_node(state, state.focus_node_ids[0], goal, **kwargs)

    def invalidate(self, state: ActiveState, reason: str) -> ActiveState:
        return replace(
            state,
            invalidated=True,
            invalidation_reason=str(reason),
        )

    def rehydrate(self, state: ActiveState) -> Dict[str, Any]:
        """Resolve active references back to exact canonical graph evidence."""

        self._require_fresh(state)
        nodes = []
        missing_nodes = []
        for node_id in state.active_node_ids:
            node = self.graph.node(node_id)
            if node is None:
                missing_nodes.append(node_id)
                continue
            nodes.append(node.to_dict())

        relationships = []
        missing_edges = []
        active_ids = set(state.active_node_ids)
        for edge_id in state.active_edge_ids:
            edge = self._edge_by_id.get(edge_id)
            if edge is None:
                missing_edges.append(edge_id)
                continue
            if edge.source not in active_ids or edge.target not in active_ids:
                continue
            relationships.append(edge.to_dict())

        if missing_nodes or missing_edges:
            detail = "missing active references: nodes=%s edges=%s" % (
                ",".join(missing_nodes[:8]),
                ",".join(missing_edges[:8]),
            )
            raise ActiveStateInvalidated(detail)

        return {
            "schema": "feynmap.active_context",
            "schema_version": "1.0.0",
            "snapshot_id": self.snapshot_id,
            "task": state.task,
            "step": state.step,
            "focus_node_ids": list(state.focus_node_ids),
            "regions": list(state.active_region_ids),
            "nodes": nodes,
            "relationships": relationships,
            "task_memory": {
                "concepts": list(state.concepts),
                "open_questions": list(state.open_questions),
                "contradictions": list(state.contradictions),
            },
            "grounding": {
                "rule": "Nodes and relationships are rehydrated from the immutable canonical graph; active state stores references only.",
            },
        }

    def metrics(self, state: ActiveState) -> Dict[str, int]:
        context = self.rehydrate(state)
        working_tokens = estimate_tokens(context)
        cumulative = state.cumulative_delivered_tokens
        return {
            "compact_state_tokens": state.compact_tokens,
            "working_context_tokens": working_tokens,
            "cumulative_delivered_tokens": cumulative,
            "context_growth_avoided_tokens": max(0, cumulative - working_tokens),
        }

    def _require_fresh(self, state: ActiveState) -> None:
        if state.invalidated:
            raise ActiveStateInvalidated(
                state.invalidation_reason or "active state was explicitly invalidated"
            )
        if state.snapshot_id != self.snapshot_id:
            raise ActiveStateInvalidated(
                "snapshot changed from %s to %s; re-expand from canonical graph"
                % (state.snapshot_id, self.snapshot_id)
            )

    def _transition(
        self,
        *,
        previous: Optional[ActiveState],
        retrieval: SparseContextResult,
        root_node_id: str,
        goal: str,
        task: str,
        open_questions: Sequence[str],
        contradictions: Sequence[str],
    ) -> ActiveStateTransition:
        budget = self.budget
        latest_nodes = tuple(retrieval.context.selected_node_ids)
        latest_edges = tuple(retrieval.context.selected_edge_ids)
        latest_set = set(latest_nodes)

        current_regions: List[str] = []
        route = retrieval.activation.route
        if route is not None:
            current_regions.extend(route.selected_regions)
        for node_id in latest_nodes:
            region_id = self.region_index.region_for_node(node_id)
            if region_id:
                current_regions.append(region_id)

        previous_nodes = tuple(previous.active_node_ids) if previous is not None else ()
        previous_set = set(previous_nodes)
        previous_focus = tuple(previous.focus_node_ids) if previous is not None else ()
        previous_regions = tuple(previous.active_region_ids) if previous is not None else ()

        connected_prior: List[str] = []
        same_region_prior: List[str] = []
        current_region_set = set(current_regions)
        for node_id in previous_nodes:
            if node_id in latest_set or self.graph.node(node_id) is None:
                continue
            if self._connected_to_any(node_id, latest_set):
                connected_prior.append(node_id)
                continue
            region_id = self.region_index.region_for_node(node_id)
            if region_id and region_id in current_region_set:
                same_region_prior.append(node_id)

        active_nodes = _dedupe(
            list(latest_nodes)
            + list(previous_focus)
            + connected_prior
            + same_region_prior,
            budget.max_nodes,
        )
        active_set = set(active_nodes)

        focus = _dedupe(
            list(
                node.id
                for node in retrieval.activation.search.roots
                if node.id in active_set
            )
            + [root_node_id]
            + list(previous_focus),
            min(8, budget.max_nodes),
        )

        active_regions = _dedupe(
            current_regions + list(previous_regions),
            budget.max_regions,
        )

        prior_edge_ids = tuple(previous.active_edge_ids) if previous is not None else ()
        edge_ids: List[str] = []
        for edge_id in list(latest_edges) + list(prior_edge_ids):
            edge = self._edge_by_id.get(edge_id)
            if edge is None:
                continue
            if edge.source in active_set and edge.target in active_set:
                edge_ids.append(edge.id)
        for edge in self.graph.edges:
            if edge.source in active_set and edge.target in active_set:
                edge_ids.append(edge.id)
        active_edges = _dedupe(edge_ids, budget.max_edges)

        concepts = _dedupe(
            list(_terms(task))
            + list(_terms(goal))
            + (list(previous.concepts) if previous is not None else []),
            budget.max_concepts,
        )
        questions = _dedupe(open_questions, budget.max_open_questions)
        conflicts = _dedupe(contradictions, budget.max_contradictions)

        retrieval_record = ActiveRetrieval(
            query=str(goal),
            root_node_id=str(root_node_id),
            stage=str(retrieval.activation.stage),
            effort=str(retrieval.activation.effort),
            region_ids=_dedupe(current_regions, budget.max_regions),
            node_ids=tuple(latest_nodes),
            edge_ids=tuple(latest_edges),
            delivered_tokens=int(retrieval.context.delivered_tokens),
        )
        history = list(previous.retrievals) if previous is not None else []
        history.append(retrieval_record)
        history = history[-budget.max_retrievals:]

        state = ActiveState(
            snapshot_id=self.snapshot_id,
            task=str(task),
            step=(previous.step + 1) if previous is not None else 1,
            focus_node_ids=focus,
            active_node_ids=active_nodes,
            active_edge_ids=active_edges,
            active_region_ids=active_regions,
            concepts=concepts,
            open_questions=questions,
            contradictions=conflicts,
            retrievals=tuple(history),
        )

        rehydrated = self.rehydrate(state)
        working_tokens = estimate_tokens(rehydrated)
        return ActiveStateTransition(
            state=state,
            retrieval=retrieval,
            reused_node_ids=tuple(
                node_id for node_id in active_nodes
                if node_id in previous_set and node_id in active_set
            ),
            introduced_node_ids=tuple(
                node_id for node_id in active_nodes
                if node_id not in previous_set
            ),
            dropped_node_ids=tuple(
                node_id for node_id in previous_nodes
                if node_id not in active_set
            ),
            working_context_tokens=working_tokens,
        )

    def _connected_to_any(self, node_id: str, targets: Set[str]) -> bool:
        if not targets:
            return False
        for edge in self.graph.outgoing(node_id):
            if edge.target in targets:
                return True
        for edge in self.graph.incoming(node_id):
            if edge.source in targets:
                return True
        return False
