"""FeynMap: grounded semantic infrastructure for AI-assisted software engineering."""
from .core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode, SourceLocation
from .engine import FeynMapEngine
from .migration import MigrationPlanner
from .query import FeynMapQuery

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
    "MigrationPlanner", "NodeKind", "SemanticEdge", "SemanticGraph",
    "SemanticNode", "SourceLocation",
]
