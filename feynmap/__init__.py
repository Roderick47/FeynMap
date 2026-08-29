"""FeynMap: grounded semantic infrastructure for AI-assisted software engineering."""
from .context import ContextBudget, StoredSnapshotContext, estimate_tokens
from .core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from .diff import diff_file_inventories, diff_graphs, diff_snapshots, diff_store_snapshots
from .engine import FeynMapEngine
from .grounding import GROUNDING_TOOL_CONTRACT_VERSION, GROUNDING_TOOLS, GroundingService, GroundingTool
from .incremental import IncrementalPlan, analyze_incrementally, incremental_snapshot, plan_incremental_analysis
from .integration import IntegrationResolver, add_contract, contracts
from .migration import MigrationPlanner
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
    "ContextBudget", "EdgeKind", "Evidence", "EvidenceKind", "FeynMapEngine", "FeynMapQuery",
    "FileFingerprint", "GROUNDING_TOOL_CONTRACT_VERSION", "GROUNDING_TOOLS", "GroundingService",
    "GroundingTool", "IncrementalPlan", "IntegrationResolver", "MigrationPlanner", "NodeKind",
    "RepositorySnapshot", "SemanticEdge", "SemanticGraph", "SemanticNode", "SnapshotStore",
    "SourceLocation", "StoredSnapshotContext", "add_contract", "analyze_incrementally",
    "capture_and_store", "capture_repository_snapshot", "contracts", "diff_file_inventories",
    "diff_graphs", "diff_snapshots", "diff_store_snapshots", "estimate_tokens",
    "incremental_snapshot", "plan_incremental_analysis",
]
