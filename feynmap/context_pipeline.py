"""Runtime composition of S2 adaptive activation and S3 minimal context."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .adaptive import AdaptiveSearchResult, AdaptiveSparseSearch
from .core import SemanticGraph
from .judgment.contracts import JudgmentProvider
from .minimal_context import (
    MinimalContextBudget,
    MinimalContextPacker,
    MinimalContextResult,
)


@dataclass(frozen=True)
class SparseContextResult:
    activation: AdaptiveSearchResult
    context: MinimalContextResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activation": self.activation.to_dict(),
            "context": self.context.to_dict(),
        }


class SparseContextPipeline:
    """Produce minimal grounded downstream context with adaptive effort."""

    def __init__(
        self,
        graph: SemanticGraph,
        provider: Optional[JudgmentProvider] = None,
        *,
        region_limit: int = 8,
        region_seed_limit: int = 12,
    ) -> None:
        self.graph = graph
        self.search = AdaptiveSparseSearch(
            graph,
            provider=provider,
            region_limit=region_limit,
            region_seed_limit=region_seed_limit,
        )
        self.packer = MinimalContextPacker(graph)

    def from_node(
        self,
        node: str,
        goal: str,
        *,
        context_budget: Optional[MinimalContextBudget] = None,
        max_depth: int = 4,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> SparseContextResult:
        activation = self.search.from_node(
            node,
            goal,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        context = self.packer.pack(
            activation.search,
            budget=context_budget,
        )
        return SparseContextResult(
            activation=activation,
            context=context,
        )

    def concept(
        self,
        concept: str,
        *,
        context_budget: Optional[MinimalContextBudget] = None,
        seed_limit: int = 8,
        candidate_limit: int = 64,
        max_depth: int = 3,
        beam_width: int = 8,
        max_nodes: int = 64,
        direction: str = "both",
    ) -> SparseContextResult:
        activation = self.search.concept(
            concept,
            seed_limit=seed_limit,
            candidate_limit=candidate_limit,
            max_depth=max_depth,
            beam_width=beam_width,
            max_nodes=max_nodes,
            direction=direction,
        )
        context = self.packer.pack(
            activation.search,
            budget=context_budget,
        )
        return SparseContextResult(
            activation=activation,
            context=context,
        )
