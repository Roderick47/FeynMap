"""Bounded source-backed behavioral context layered over S3 symbol delivery."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .behavior import BehaviorObservation, GroundedBehaviorExtractor
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
    """Attach the smallest useful source behavior to an existing S3 result.

    The builder can only inspect symbols already selected by S3.  It does not
    mutate or expand the semantic graph.  If a task needs an unselected or
    unresolved symbol, the result stays insufficient and the caller may choose
    a separate bounded expansion step.
    """

    _LABEL_RANK = {
        RelevanceLabel.ESSENTIAL: 0,
        RelevanceLabel.SUPPORTING: 1,
        RelevanceLabel.UNCERTAIN: 2,
        RelevanceLabel.IRRELEVANT: 3,
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

        selected: List[BehaviorObservation] = []
        selected_rows: List[Dict[str, Any]] = []
        source_chars = 0
        omitted = 0
        omitted_critical = 0
        for observation, decision in useful:
            is_critical = (
                observation.id in dimension_witness_ids
                or decision.label == RelevanceLabel.ESSENTIAL
            )
            if len(selected) >= requested.max_observations:
                omitted += 1
                if is_critical:
                    omitted_critical += 1
                continue
            row = observation.to_dict(include_source=True)
            row["relevance"] = decision.to_dict()
            source_facts = dict(structured_behavior_facts(observation))
            if source_facts:
                row["source_facts"] = source_facts
            if observation.id in dimension_witness_ids:
                row["task_dimension_witness"] = True
            source_text = str(row.get("source", ""))
            if source_text and source_chars + len(source_text) > requested.max_source_chars:
                # Keep the structured source-derived fact and exact location;
                # drop only the redundant inline witness when its char budget
                # is exhausted.
                row.pop("source", None)
                source_text = ""
            trial_rows = selected_rows + [row]
            trial = self._behavior_payload(profile, trial_rows, context)
            if estimate_tokens(trial) > requested.max_tokens:
                omitted += 1
                if is_critical:
                    omitted_critical += 1
                continue
            selected.append(observation)
            selected_rows.append(row)
            source_chars += len(source_text)

        delivered_ids = {item.id for item in selected}
        selected_rows.sort(
            key=lambda row: (
                str(row.get("location", {}).get("path", "")),
                int(row.get("order", 0)),
                str(row.get("id", "")),
            )
        )
        behavior_payload = self._behavior_payload(profile, selected_rows, context)
        behavior_payload["sequences"] = self._sequences(selected)
        behavior_payload["omitted_relevant_observations"] = int(omitted)
        behavior_payload["omitted_critical_observations"] = int(omitted_critical)
        behavior_payload["candidate_observations"] = len(candidates)
        behavior_payload["delivered_observations"] = len(selected)
        behavior_payload["source_witness_chars"] = source_chars
        behavior_payload["selection"] = {
            "judge": self.judge.__class__.__name__,
            "rule": "reserve task-critical behavior by evidence channel, then essential > supporting > uncertain",
            "unknown_is_not_false": True,
            "selected_symbol_boundary": True,
        }

        sufficiency = self.judge.sufficiency(
            task,
            selected,
            profile,
            unresolved_identifiers=context.unresolved_query_identifiers,
            # Supporting/uncertain enrichment can be dropped.  Only omitted
            # task-dimension witnesses or provider-essential facts make the
            # packet fail closed.
            omitted_relevant=omitted_critical,
        )
        behavior_payload["sufficiency"] = sufficiency.to_dict()
        if context.unresolved_query_identifiers:
            behavior_payload["unresolved_query_identifiers"] = list(
                context.unresolved_query_identifiers
            )

        combined: Dict[str, Any] = dict(context.payload)
        combined["behavioral_evidence"] = behavior_payload
        behavior_tokens = estimate_tokens(behavior_payload)
        total_tokens = estimate_tokens(combined)
        sufficient = bool(
            context.sufficient
            and sufficiency.sufficient
            and omitted_critical == 0
        )
        # Sanity check: every delivered row must correspond to an extracted,
        # source-backed observation from a selected symbol.
        row_ids = {str(row.get("id")) for row in selected_rows}
        if row_ids != delivered_ids:
            raise ValueError("behavioral envelope observation identity mismatch")
        selected_symbol_ids = set(context.selected_node_ids)
        if any(item.symbol_id not in selected_symbol_ids for item in selected):
            raise ValueError("behavioral envelope escaped selected symbol boundary")

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
        """Prevent one evidence channel from replacing the causal path.

        A test task needs production behavior *and* test corroboration; a
        migration task needs the migration operation *and* the implementation
        or default it invokes.  Ordinary implementation tasks reserve only
        implementation-channel witnesses.  This avoids repeating P2.1's
        mistake one level deeper by treating all observations of one kind as
        interchangeable.
        """
        critical_kinds = {
            kind
            for kind, weight in profile.category_weights.items()
            if float(weight) >= 0.80
        }
        channels = {IMPLEMENTATION}
        if profile.task_type == "test_behavior":
            channels.add(TEST)
        if profile.task_type == "migration_behavior":
            channels.add(MIGRATION)

        representatives: List[Tuple[BehaviorObservation, RelevanceDecision]] = []
        representative_ids = set()
        channel_rank = {IMPLEMENTATION: 0, TEST: 1, MIGRATION: 1}
        for kind in sorted(critical_kinds):
            for channel in sorted(channels, key=lambda value: (channel_rank.get(value, 9), value)):
                candidates = [
                    item
                    for item in useful
                    if item[0].kind.value == kind
                    and file_channel(item[0].location.path) == channel
                ]
                if not candidates:
                    continue
                best = min(candidates, key=self._relevance_sort_key)
                if best[0].id in representative_ids:
                    continue
                representatives.append(best)
                representative_ids.add(best[0].id)
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

    @staticmethod
    def _behavior_payload(
        profile: TaskEvidenceProfile,
        rows: Sequence[Mapping[str, Any]],
        context: MinimalContextResult,
    ) -> Dict[str, Any]:
        return {
            "schema": BEHAVIOR_SCHEMA,
            "task_profile": profile.to_dict(),
            "observations": [dict(row) for row in rows],
            "grounding": {
                "truth_source": "repository source selected by S3 semantic symbols",
                "relevance_not_truth": "task judge may rank observations but cannot change evidence confidence",
                "source_order_scope": "ordering is local source order within each symbol; it is not global runtime order",
                "minimal_source_witnesses": True,
                "structured_source_facts": "reads/literals/operators/calls/transforms are derived only from each observation's source witness",
                "base_delivery_sufficient": bool(context.sufficient),
            },
        }

    @staticmethod
    def _sequences(observations: Sequence[BehaviorObservation]) -> Dict[str, List[str]]:
        by_symbol: Dict[str, List[BehaviorObservation]] = {}
        for item in observations:
            by_symbol.setdefault(item.symbol_id, []).append(item)
        return {
            symbol_id: [item.id for item in sorted(items, key=lambda value: (value.order, value.id))]
            for symbol_id, items in sorted(by_symbol.items())
        }
