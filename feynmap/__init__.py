"""FeynMap: evidence-backed sparse knowledge activation for AI systems."""
from .activation import ActivationMetrics, measure_guided_search
from .active_state import (
    ACTIVE_STATE_SCHEMA,
    ACTIVE_STATE_SCHEMA_VERSION,
    ActiveRetrieval,
    ActiveState,
    ActiveStateBudget,
    ActiveStateInvalidated,
    ActiveStateRuntime,
    ActiveStateTransition,
)
from .adaptive import AdaptiveSearchResult, AdaptiveSparseSearch
from .context import ContextBudget, StoredSnapshotContext, estimate_tokens
from .core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from .diff import diff_file_inventories, diff_graphs, diff_snapshots, diff_store_snapshots
from .engine import FeynMapEngine
from .evaluation import evaluate_graph
from .grounding import GROUNDING_TOOL_CONTRACT_VERSION, GROUNDING_TOOLS, GroundingService, GroundingTool
from .incremental import IncrementalPlan, analyze_incrementally, incremental_snapshot, plan_incremental_analysis
from .integration import IntegrationResolver, add_contract, contracts
from .migration import MigrationPlanner
from .minimal_context import MinimalContextBudget, MinimalContextPacker, MinimalContextResult
from .context_pipeline import SparseContextPipeline, SparseContextResult
from .query import FeynMapQuery
from .snapshots import FileFingerprint, RepositorySnapshot, SnapshotStore, capture_and_store, capture_repository_snapshot

__version__ = "3.0.0a1"


def __getattr__(name):
    """Lazy compatibility exports for the V2 Python API."""
    if name == "FeynExtractor":
        from feyn_parser import FeynExtractor
        return FeynExtractor
    if name == "FeynNotator":
        from feyn_notation import FeynNotator
        return FeynNotator
    raise AttributeError(name)


__all__ = [
    "ACTIVE_STATE_SCHEMA", "ACTIVE_STATE_SCHEMA_VERSION", "ActivationMetrics",
    "ActiveRetrieval", "ActiveState", "ActiveStateBudget", "ActiveStateInvalidated",
    "ActiveStateRuntime", "ActiveStateTransition", "AdaptiveSearchResult",
    "AdaptiveSparseSearch", "ContextBudget", "EdgeKind", "Evidence", "EvidenceKind",
    "FeynMapEngine", "FeynMapQuery", "FileFingerprint",
    "GROUNDING_TOOL_CONTRACT_VERSION", "GROUNDING_TOOLS", "GroundingService",
    "GroundingTool", "IncrementalPlan", "IntegrationResolver", "MigrationPlanner",
    "MinimalContextBudget", "MinimalContextPacker", "MinimalContextResult", "NodeKind",
    "RepositorySnapshot", "SemanticEdge", "SemanticGraph", "SemanticNode", "SnapshotStore",
    "SparseContextPipeline", "SparseContextResult", "SourceLocation",
    "StoredSnapshotContext", "add_contract", "analyze_incrementally",
    "capture_and_store", "capture_repository_snapshot", "contracts",
    "diff_file_inventories", "diff_graphs", "diff_snapshots", "diff_store_snapshots",
    "estimate_tokens", "incremental_snapshot", "measure_guided_search",
    "plan_incremental_analysis", "evaluate_graph",
]
