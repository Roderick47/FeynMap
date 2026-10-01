"""Opt-in composition for task-conditioned source evidence.

This is deliberately a new surface rather than a change to SparseContextPipeline's
legacy defaults. P2.4 callers opt into symbol-evidence delivery, a bounded
source-backed continuation over already activated behavior dependencies, and
bounded behavioral evidence; existing callers continue to receive the unchanged
S3 payload unless they choose this pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .behavioral_context import BehaviorEvidenceBudget, BehavioralContextResult
from .behavioral_delivery import (
    BehavioralContinuationResult,
    BehavioralSymbolContinuation,
    TaskConditionedBehavioralContextBuilder,
)
from .context_pipeline import SparseContextPipeline, SparseContextResult
from .core import SemanticGraph
from .delivery_channels import DeliveryChannelPolicy
from .judgment.contracts import JudgmentProvider
from .minimal_context import MinimalContextBudget
from .relevance import JudgmentProviderRelevanceJudge, RelevanceJudge


@dataclass(frozen=True)
class TaskConditionedEvidenceResult:
    sparse: SparseContextResult
    continuation: BehavioralContinuationResult
    behavioral: BehavioralContextResult

    @property
    def sufficient(self) -> bool:
        return bool(self.behavioral.sufficient)

    @property
    def payload(self):
        return self.behavioral.payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activation": self.sparse.activation.to_dict(),
            "continuation": self.continuation.to_dict(),
            "context": self.sparse.context.to_dict(),
            "behavioral": self.behavioral.to_dict(),
            "sufficient": self.sufficient,
        }


class TaskConditionedEvidencePipeline:
    """Build a sparse source-verifiable evidence packet for one task.

    The optional activation provider participates only in adaptive search. The
    optional relevance provider participates only in ranking already-extracted
    source observations and sufficiency judgment. Neither can mutate semantic
    graph truth or behavioral evidence confidence.

    P2.4c additionally permits one best continuation through source-backed
    behavioral edges, but only among nodes that S2 already activated. This
    repairs an S3 omission without allowing the behavior layer to invent or
    independently discover source symbols.
    """

    def __init__(
        self,
        graph: SemanticGraph,
        project_root: Path,
        *,
        activation_provider: Optional[JudgmentProvider] = None,
        relevance_provider: Optional[JudgmentProvider] = None,
        relevance_judge: Optional[RelevanceJudge] = None,
        behavior_budget: Optional[BehaviorEvidenceBudget] = None,
        region_limit: int = 8,
        region_seed_limit: int = 12,
    ) -> None:
        if relevance_provider is not None and relevance_judge is not None:
            raise ValueError("pass relevance_provider or relevance_judge, not both")
        judge = relevance_judge
        if judge is None and relevance_provider is not None:
            judge = JudgmentProviderRelevanceJudge(relevance_provider)
        self.sparse = SparseContextPipeline(
            graph,
            provider=activation_provider,
            region_limit=region_limit,
            region_seed_limit=region_seed_limit,
        )
        self.continuation = BehavioralSymbolContinuation(
            graph,
            max_added_nodes=1,
            max_seed_anchors=1,
        )
        self.behavior = TaskConditionedBehavioralContextBuilder(
            graph,
            Path(project_root),
            judge=judge,
            budget=behavior_budget,
        )
        self.delivery_policy = DeliveryChannelPolicy(mode="symbol_evidence")

    def concept(
        self,
        task: str,
        *,
        context_budget: Optional[MinimalContextBudget] = None,
        behavior_budget: Optional[BehaviorEvidenceBudget] = None,
        seed_limit: int = 8,
        candidate_limit: int = 64,
        max_depth: int = 3,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> TaskConditionedEvidenceResult:
        requested_context = (context_budget or MinimalContextBudget()).normalized()
        sparse = self.sparse.concept(
            task,
            context_budget=requested_context,
            delivery_policy=self.delivery_policy,
            seed_limit=seed_limit,
            candidate_limit=candidate_limit,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        continuation = self.continuation.extend(
            task,
            sparse.activation.search,
            sparse.context,
            budget=requested_context,
            delivery_policy=self.delivery_policy,
        )
        sparse = SparseContextResult(
            activation=sparse.activation,
            context=continuation.context,
        )
        behavioral = self.behavior.build(
            task,
            sparse.context,
            budget=behavior_budget,
        )
        return TaskConditionedEvidenceResult(
            sparse=sparse,
            continuation=continuation,
            behavioral=behavioral,
        )

    def from_node(
        self,
        node: str,
        task: str,
        *,
        context_budget: Optional[MinimalContextBudget] = None,
        behavior_budget: Optional[BehaviorEvidenceBudget] = None,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> TaskConditionedEvidenceResult:
        requested_context = (context_budget or MinimalContextBudget()).normalized()
        sparse = self.sparse.from_node(
            node,
            task,
            context_budget=requested_context,
            delivery_policy=self.delivery_policy,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        continuation = self.continuation.extend(
            task,
            sparse.activation.search,
            sparse.context,
            budget=requested_context,
            delivery_policy=self.delivery_policy,
        )
        sparse = SparseContextResult(
            activation=sparse.activation,
            context=continuation.context,
        )
        behavioral = self.behavior.build(
            task,
            sparse.context,
            budget=behavior_budget,
        )
        return TaskConditionedEvidenceResult(
            sparse=sparse,
            continuation=continuation,
            behavioral=behavioral,
        )
