"""FeynMap: grounded semantic infrastructure for AI-assisted software engineering."""
from .core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from .engine import FeynMapEngine
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
    "EdgeKind", "Evidence", "EvidenceKind", "FeynMapEngine", "FeynMapQuery",
    "FileFingerprint", "IntegrationResolver", "MigrationPlanner", "NodeKind",
    "RepositorySnapshot", "SemanticEdge", "SemanticGraph", "SemanticNode",
    "SnapshotStore", "SourceLocation", "add_contract", "capture_and_store",
    "capture_repository_snapshot", "contracts",
]
