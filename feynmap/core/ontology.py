"""Language-agnostic ontology used by FeynMap's semantic graph."""
from enum import Enum


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class NodeKind(StringEnum):
    REPOSITORY = "repository"
    MODULE = "module"
    FILE = "file"
    SYMBOL = "symbol"
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    TYPE = "type"
    DATA_MODEL = "data_model"
    HANDLER = "handler"
    SERVICE = "service"
    TRANSFORMER = "transformer"
    MIDDLEWARE = "middleware"
    UI_SURFACE = "ui_surface"
    CLIENT_LOGIC = "client_logic"
    DATABASE = "database"
    QUEUE = "queue"
    EXTERNAL_SYSTEM = "external_system"
    UNKNOWN = "unknown"


class EdgeKind(StringEnum):
    CALLS = "calls"
    IMPORTS = "imports"
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    READS = "reads"
    WRITES = "writes"
    MUTATES = "mutates"
    CREATES = "creates"
    DELETES = "deletes"
    RETURNS = "returns"
    USES_DATA = "uses_data"
    SERIALIZES = "serializes"
    VALIDATES = "validates"
    PERSISTS = "persists"
    REQUESTS = "requests"
    EMITS = "emits"
    SUBSCRIBES = "subscribes"
    AWAITS = "awaits"
    IMPLEMENTS = "implements"
    EXTENDS = "extends"
    OWNS = "owns"
    FLOWS_TO = "flows_to"
    OBSERVES = "observes"
    RELATED_TO = "related_to"


class EvidenceKind(StringEnum):
    STATIC = "static_analysis"
    FRAMEWORK = "framework_analysis"
    RUNTIME = "runtime_trace"
    TEST = "test_observation"
    HISTORY = "repository_history"
    HEURISTIC = "heuristic"
    AI_INFERENCE = "ai_inference"


class ConfidenceTier(StringEnum):
    VERIFIED = "verified"
    SUPPORTED = "supported"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


def confidence_tier(score: float, evidence_count: int = 0, has_ai_only_evidence: bool = False) -> ConfidenceTier:
    """Translate a numeric confidence score into a human-facing evidence tier."""
    if evidence_count <= 0:
        return ConfidenceTier.UNKNOWN
    if score >= 0.95 and not has_ai_only_evidence:
        return ConfidenceTier.VERIFIED
    if score >= 0.75:
        return ConfidenceTier.SUPPORTED
    if score >= 0.40:
        return ConfidenceTier.INFERRED
    return ConfidenceTier.UNKNOWN
