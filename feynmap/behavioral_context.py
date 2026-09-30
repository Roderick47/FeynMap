"""Bounded source-backed behavioral context layered over S3 symbol delivery."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .behavior import BehaviorKind, BehaviorObservation, GroundedBehaviorExtractor
from .behavior_coverage import behavior_coverage
from .behavior_facts import structured_behavior_facts
from .context import estimate_tokens
from .core import SemanticGraph
from .delivery_channels import IMPLEMENTATION, MIGRATION, TEST, file_channel
from .minimal_context import MinimalContextResult
from .relevance import (
    DeterministicRelevanceJudge,
    RelevanceDecision,
    RelevanceJudge,
    RelevanceLabel,
    SufficiencyDecision,
    TaskEvidenceProfile,
)


BEHAVIOR_SCHEMA = "feynmap.behavioral_evidence.v1"


@dataclass(frozen=True)
class BehaviorEvidenceBudget:
    max_tokens: int = 1400
    max_observations: int = 32
    max_source_chars: int = 3600

    def normalized(self) -> "BehaviorEvidenceBudget":
        return BehaviorEvidenceBudget(
            max_tokens=max(128, int(self.max_tokens)),
            max_observations=max(1, int(self.max_observations)),
            max_source_chars=max(0, int(self.max_source_chars)),
        )


@dataclass(frozen=True)
class BehavioralContextResult:
    payload: Mapping[str, Any]
    profile: TaskEvidenceProfile
    delivered_observations: Sequence[BehaviorObservation]
    decisions: Mapping[str, RelevanceDecision]
    sufficiency: SufficiencyDecision
    candidate_observations: int
    omitted_relevant_observations: int
    omitted_critical_observations: int
    behavior_tokens: int
    total_tokens: int
    sufficient: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload": dict(self.payload),
            "task_profile": self.profile.to_dict(),
            "candidate_observations": int(self.candidate_observations),
            "delivered_observations": len(self.delivered_observations),
            "omitted_relevant_observations": int(self.omitted_relevant_observations),
            "omitted_critical_observations": int(self.omitted_critical_observations),
            "behavior_tokens": int(self.behavior_tokens),
            "total_tokens": int(self.total_tokens),
            "sufficiency": self.sufficiency.to_dict(),
            "sufficient": bool(self.sufficient),
        }


class BehavioralContextBuilder:
    """Attach the smallest useful source behavior to an existing S3 result."""

    _LABEL_RANK = {
        RelevanceLabel.ESSENTIAL: 0,
        RelevanceLabel.SUPPORTING: 1,
        RelevanceLabel.UNCERTAIN: 2,
        RelevanceLabel.IRRELEVANT: 3,
    }

    _TASK_CHANNEL_KINDS = {
        "failure_behavior": {
            IMPLEMENTATION: (
                BehaviorKind.CONDITION,
                BehaviorKind.RAISE,
                BehaviorKind.CALL,
            ),
        },
        "return_behavior": {
            IMPLEMENTATION: (
                BehaviorKind.RETURN,
                BehaviorKind.CALL,
            ),
        },
        "state_change": {
            IMPLEMENTATION: (
                BehaviorKind.MUTATION,
                BehaviorKind.ASSIGNMENT,
                BehaviorKind.CONDITION,
                BehaviorKind.CALL,
                BehaviorKind.RETURN,
            ),
        },
        "test_behavior": {
            IMPLEMENTATION: (
                BehaviorKind.CONDITION,
                BehaviorKind.RAISE,
                BehaviorKind.MUTATION,
                BehaviorKind.CALL,
            ),
            TEST: (
                BehaviorKind.ASSERTION,
                BehaviorKind.CALL,
            ),
        },
        "migration_behavior": {
            MIGRATION: (
                BehaviorKind.CONDITION,
                BehaviorKind.MUTATION,
                BehaviorKind.ASSIGNMENT,
                BehaviorKind.CALL,
                BehaviorKind.RETURN,
            ),
            IMPLEMENTATION: (
                BehaviorKind.RETURN,
                BehaviorKind.CALL,
            ),
        },
        "transformation": {
            IMPLEMENTATION: (
                BehaviorKind.TRANSFORM,
                BehaviorKind.RETURN,
                BehaviorKind.CALL,
            ),
        },
        "side_effect": {
            IMPLEMENTATION: (
                BehaviorKind.SIDE_EFFECT,
                BehaviorKind.CALL,
                BehaviorKind.RETURN,
                BehaviorKind.CONDITION,
                BehaviorKind.MUTATION,
            ),
        },
        "general_behavior": {
            IMPLEMENTATION: (
                BehaviorKind.CALL,
                BehaviorKind.RETURN,
                BehaviorKind.CONDITION,
                BehaviorKind.MUTATION,
            ),
        },
    }

    def __init__(
        self,
        graph: SemanticGraph,
        project_root: Path,
        *,
        judge: Optional[RelevanceJudge] = None,
        budget: Optional[BehaviorEvidenceBudget] = None,
    ) -> None:
        self.graph = graph
        self.extractor = GroundedBehaviorExtractor(Path(project_root))
        self.judge = judge or DeterministicRelevanceJudge()
        self.budget = (budget or BehaviorEvidenceBudget()).normalized()

    def build(
        self,
        task: str,
        context: MinimalContextResult,
        *,
        budget: Optional[BehaviorEvidenceBudget] = None,
    ) -> BehavioralContextResult:
        requested = (budget or self.budget).normalized()
        candidates = self.extractor.extract(self.graph, context.selected_node_ids)
        profile = self.judge.profile(task)
        decisions = dict(self.judge.rank(task, candidates, profile))

        useful: List[Tuple[BehaviorObservation, RelevanceDecision]] = []
        for observation in candidates:
            decision = decisions.get(observation.id)
            if decision is None or decision.label == RelevanceLabel.IRRELEVANT:
                continue
            useful.append((observation, decision))
        useful.sort(key=self._relevance_sort_key)
        useful, dimension_witness_ids = self._reserve_task_dimensions(useful, profile)

        # (observation, decision, compact model row, critical, source chars)
        entries: List[Tuple[BehaviorObservation, RelevanceDecision, Dict[str, Any], bool, int]] = []
        source_chars = 0
        omitted = 0
        omitted_critical = 0
        for observation, decision in useful:
            # Relevance drives packing order. Only explicitly reserved task
            # dimensions are hard sufficiency requirements; otherwise a broad
            # deterministic "essential" score would simply recreate crowding.
            is_critical = observation.id in dimension_witness_ids
            if len(entries) >= requested.max_observations:
                omitted += 1
                if is_critical:
                    omitted_critical += 1
                continue
            row = self._model_row(
                observation,
                decision,
                dimension_witness=is_critical,
            )
            source_text = str(row.get("source", ""))
            if source_text and source_chars + len(source_text) > requested.max_source_chars:
                row.pop("source", None)
                source_text = ""
            entries.append((observation, decision, row, is_critical, len(source_text)))
            source_chars += len(source_text)

        behavior_payload, sufficiency = self._render_final_payload(
            task, profile, context, candidates, entries,
            omitted, omitted_critical, source_chars,
        )

        # Enforce the cap on the complete model-facing behavioral envelope.
        while entries and estimate_tokens(behavior_payload) > requested.max_tokens:
            remove_index = self._least_valuable_entry(entries, prefer_noncritical=True)
            _, _, _, was_critical, chars = entries.pop(remove_index)
            source_chars -= chars
            omitted += 1
            if was_critical:
                omitted_critical += 1
            behavior_payload, sufficiency = self._render_final_payload(
                task, profile, context, candidates, entries,
                omitted, omitted_critical, source_chars,
            )

        if estimate_tokens(behavior_payload) > requested.max_tokens:
            sufficiency = self.judge.sufficiency(
                task,
                (),
                profile,
                unresolved_identifiers=context.unresolved_query_identifiers,
                omitted_relevant=max(1, omitted_critical or omitted or len(useful)),
            )
            behavior_payload = {
                "schema": BEHAVIOR_SCHEMA,
                "task": self._compact_task_profile(profile),
                "observations": [],
                "budget_exhausted": True,
                "unresolved": list(context.unresolved_query_identifiers),
                "sufficiency": sufficiency.to_dict(),
                "grounding": {"source": True, "unknown_is_not_false": True},
            }
            entries = []
            source_chars = 0
            omitted = max(omitted, len(useful))
            omitted_critical = max(omitted_critical, 1 if useful else 0)

        selected = [entry[0] for entry in entries]
        selected_rows = [entry[2] for entry in entries]
        delivered_ids = {item.id for item in selected}
        if {str(row.get("id")) for row in selected_rows} != delivered_ids:
            raise ValueError("behavioral envelope observation identity mismatch")
        selected_symbol_ids = set(context.selected_node_ids)
        if any(item.symbol_id not in selected_symbol_ids for item in selected):
            raise ValueError("behavioral envelope escaped selected symbol boundary")

        combined: Dict[str, Any] = dict(context.payload)
        combined["behavioral_evidence"] = behavior_payload
        behavior_tokens = estimate_tokens(behavior_payload)
        if behavior_tokens > requested.max_tokens:
            raise ValueError("behavioral envelope exceeded requested token budget")
        total_tokens = estimate_tokens(combined)
        sufficient = bool(
            context.sufficient
            and sufficiency.sufficient
            and omitted_critical == 0
            and not behavior_payload.get("budget_exhausted")
        )
        return BehavioralContextResult(
            payload=combined,
            profile=profile,
            delivered_observations=tuple(selected),
            decisions=decisions,
            sufficiency=sufficiency,
            candidate_observations=len(candidates),
            omitted_relevant_observations=omitted,
            omitted_critical_observations=omitted_critical,
            behavior_tokens=behavior_tokens,
            total_tokens=total_tokens,
            sufficient=sufficient,
        )

    def _model_row(
        self,
        observation: BehaviorObservation,
        decision: RelevanceDecision,
        *,
        dimension_witness: bool,
    ) -> Dict[str, Any]:
        """Compact model view; rich Evidence/Decision objects remain internal."""
        location = observation.location
        row: Dict[str, Any] = {
            "id": observation.id,
            "symbol_id": observation.symbol_id,
            "kind": observation.kind.value,
            "summary": observation.summary,
            "location": {
                "path": location.path,
                "line": location.line,
                "end_line": location.end_line,
            },
            "order": int(observation.order),
            "confidence_tier": observation.confidence_tier,
            "provenance": {
                "kind": observation.evidence.kind.value,
                "detector": observation.evidence.detector,
                "confidence": round(float(observation.evidence.confidence), 4),
            },
            "relevance": {
                "label": decision.label.value,
                "score": round(float(decision.score), 4),
            },
        }
        if observation.source:
            row["source"] = observation.source
        if observation.condition:
            row["condition"] = observation.condition
        if observation.attributes:
            row["attributes"] = dict(observation.attributes)
        facts = dict(structured_behavior_facts(observation))
        if facts:
            row["source_facts"] = facts
        if dimension_witness:
            row["task_dimension_witness"] = True
        return row

    def _render_final_payload(
        self,
        task: str,
        profile: TaskEvidenceProfile,
        context: MinimalContextResult,
        candidates: Sequence[BehaviorObservation],
        entries: Sequence[Tuple[BehaviorObservation, RelevanceDecision, Dict[str, Any], bool, int]],
        omitted: int,
        omitted_critical: int,
        source_chars: int,
    ) -> Tuple[Dict[str, Any], SufficiencyDecision]:
        selected = [entry[0] for entry in entries]
        rows = sorted(
            [entry[2] for entry in entries],
            key=lambda row: (
                str(row.get("location", {}).get("path", "")),
                int(row.get("order", 0)),
                str(row.get("id", "")),
            ),
        )
        sufficiency = self.judge.sufficiency(
            task,
            selected,
            profile,
            unresolved_identifiers=context.unresolved_query_identifiers,
            omitted_relevant=omitted_critical,
        )
        coverage = behavior_coverage(
            self.graph,
            context.selected_node_ids,
            candidates,
            selected,
            unresolved_identifiers=context.unresolved_query_identifiers,
            omitted_relevant=max(0, omitted - omitted_critical),
            omitted_critical=omitted_critical,
        )
        payload: Dict[str, Any] = {
            "schema": BEHAVIOR_SCHEMA,
            "task": self._compact_task_profile(profile),
            "observations": rows,
            "counts": {
                "candidate": len(candidates),
                "delivered": len(selected),
                "omitted": int(omitted),
                "omitted_critical": int(omitted_critical),
                "source_chars": int(source_chars),
            },
            "selection": {
                "judge": self.judge.__class__.__name__,
                "order": "task-dimension-witnesses,essential,supporting,uncertain",
            },
            "coverage": {
                "scanned_selected_symbols": len(coverage["symbols"]),
                "local_source_scan": "complete_supported_extractor",
                "transitive_runtime": "not_claimed_complete",
                "dynamic_dispatch": "unknown_unless_evidenced",
                "external_effects": "unknown_unless_evidenced",
                "unknowns": coverage["unknowns"],
                "unselected_call_targets": [
                    {
                        "callee": item["callee"],
                        "symbol_id": item["symbol_id"],
                    }
                    for item in coverage["call_targets_without_selected_behavior"][:4]
                ],
            },
            "sufficiency": sufficiency.to_dict(),
            "grounding": {
                "source_backed": True,
                "relevance_does_not_change_truth": True,
                "order_scope": "local_source_order_only",
                "unknown_is_not_false": True,
            },
        }
        if context.unresolved_query_identifiers:
            payload["unresolved"] = list(context.unresolved_query_identifiers)
        return payload, sufficiency

    @staticmethod
    def _compact_task_profile(profile: TaskEvidenceProfile) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"type": profile.task_type}
        if profile.identifiers:
            payload["identifiers"] = list(profile.identifiers)
        return payload

    def _least_valuable_entry(
        self,
        entries: Sequence[Tuple[BehaviorObservation, RelevanceDecision, Dict[str, Any], bool, int]],
        *,
        prefer_noncritical: bool,
    ) -> int:
        candidates = list(enumerate(entries))
        if prefer_noncritical:
            noncritical = [item for item in candidates if not item[1][3]]
            if noncritical:
                candidates = noncritical
        return max(
            candidates,
            key=lambda item: (
                self._LABEL_RANK[item[1][1].label],
                -float(item[1][1].score),
                item[1][0].order,
                item[0],
            ),
        )[0]

    def _relevance_sort_key(
        self, item: Tuple[BehaviorObservation, RelevanceDecision]
    ) -> Tuple[Any, ...]:
        observation, decision = item
        return (
            self._LABEL_RANK[decision.label],
            -float(decision.score),
            observation.location.path,
            observation.order,
            observation.id,
        )

    def _reserve_task_dimensions(
        self,
        useful: Sequence[Tuple[BehaviorObservation, RelevanceDecision]],
        profile: TaskEvidenceProfile,
    ) -> Tuple[List[Tuple[BehaviorObservation, RelevanceDecision]], set]:
        """Reserve only the behavior/channel pairs needed by this task type.

        For explicitly named code symbols, reserve a matching witness where the
        required behavior kind exists. This prevents a second relevant symbol
        (e.g. normalizeStatus beside formatShipmentStatus) from being displaced
        by generic high-scoring enrichment.
        """
        requirements = self._TASK_CHANNEL_KINDS.get(
            profile.task_type,
            self._TASK_CHANNEL_KINDS["general_behavior"],
        )
        representatives: List[Tuple[BehaviorObservation, RelevanceDecision]] = []
        representative_ids = set()
        channel_rank = {IMPLEMENTATION: 0, TEST: 1, MIGRATION: 1}

        def reserve_best(candidates):
            if not candidates:
                return
            best = min(candidates, key=self._relevance_sort_key)
            if best[0].id not in representative_ids:
                representatives.append(best)
                representative_ids.add(best[0].id)

        for channel, kinds in requirements.items():
            for kind in kinds:
                candidates = [
                    item
                    for item in useful
                    if item[0].kind == kind
                    and file_channel(item[0].location.path) == channel
                ]
                if not candidates:
                    continue
                reserve_best(candidates)
                for identifier in profile.identifiers:
                    named = []
                    for item in candidates:
                        node = self.graph.node(item[0].symbol_id)
                        if node is not None and node.name == identifier:
                            named.append(item)
                    reserve_best(named)

        representatives.sort(
            key=lambda item: (
                channel_rank.get(file_channel(item[0].location.path), 9),
                -float(profile.category_weights.get(item[0].kind.value, 0.0)),
                -float(item[1].score),
                item[0].location.path,
                item[0].order,
            )
        )
        remainder = [item for item in useful if item[0].id not in representative_ids]
        return representatives + remainder, representative_ids
