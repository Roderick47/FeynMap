"""
Configuration system for FeynMap - makes it portable across supported Python frameworks.
"""

import inspect
from pathlib import Path
from typing import Optional, Union

try:
    from .framework_detection import FrameworkDetectionResult, FrameworkDetector
    from .component_metrics import install_component_metric_calculator
except ImportError:
    from framework_detection import FrameworkDetectionResult, FrameworkDetector
    from component_metrics import install_component_metric_calculator


class FrameworkConfig:
    """Base configuration for web framework detection patterns."""

    framework_name = "generic"

    def __init__(self):
        self.model_patterns = []
        self.view_patterns = []
        self.serializer_patterns = []
        self.template_extensions = []
        self.code_extensions = [".py"]
        self.template_patterns = {}
        self.orm_patterns = []
        self.exclude_dirs = ["venv", ".venv", "env", "__pycache__", ".git", "node_modules"]
        self.detection_result: Optional[FrameworkDetectionResult] = None

    def get_model_detection_rules(self):
        return self.model_patterns

    def get_view_detection_rules(self):
        return self.view_patterns

    def get_serializer_detection_rules(self):
        return self.serializer_patterns

    def get_template_patterns(self):
        return self.template_patterns

    def get_orm_patterns(self):
        return self.orm_patterns


class DjangoConfig(FrameworkConfig):
    framework_name = "django"

    def __init__(self):
        super().__init__()
        self.model_patterns = [{"type": "class_inheritance", "pattern": "models.Model"}]
        self.view_patterns = [
            {"type": "class_name_suffix", "pattern": "View"},
            {"type": "class_name_suffix", "pattern": "APIView"},
            {"type": "function_name_contains", "pattern": "view"},
            {
                "type": "function_name_contains",
                "pattern": ["dashboard", "home", "detail", "create", "edit", "list"],
            },
        ]
        self.serializer_patterns = [
            {"type": "class_name_suffix", "pattern": "Serializer"}
        ]
        self.template_extensions = [".html"]
        self.code_extensions = [".py"]
        self.template_patterns = {
            "variables": r"{{\s*([\w\.]+)\s*}}",
            "tags": r"{%\s*[^%]+\s*%}",
            "js_functions": r"function\s+(\w+)\s*\(",
            "arrow_functions": r"(\w+)\s*=\s*(?:async\s+)?(?:function\s*\([^)]*\)|\([^)]*\))\s*=>",
            "fetch_calls": r"fetch\s*\(\s*['\"]([^'\"]+)['\"]",
            "async_functions": r"async\s+function\s+(\w+)",
            "event_listeners": r"addEventListener\s*\(\s*['\"]([^'\"]+)['\"]",
        }
        self.orm_patterns = [
            r"(\w+)\.objects\.(all|get|filter|create|update|delete)",
            r"(\w+)\.objects\.first\(\)",
            r"(\w+)\.objects\.last\(\)",
            r"(\w+)\.objects\.count\(\)",
        ]


class FlaskConfig(FrameworkConfig):
    framework_name = "flask"

    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "db.Model"},
            {"type": "class_inheritance", "pattern": "SQLAlchemy"},
        ]
        self.view_patterns = [
            {"type": "function_decorator", "pattern": "@app.route"},
            {"type": "function_decorator", "pattern": "@bp.route"},
            {
                "type": "function_name_contains",
                "pattern": ["dashboard", "home", "detail", "create", "edit", "list"],
            },
        ]
        self.serializer_patterns = [
            {"type": "class_name_suffix", "pattern": "Schema"},
            {"type": "class_inheritance", "pattern": "ma.Schema"},
        ]
        self.template_extensions = [".html", ".jinja", ".jinja2"]
        self.code_extensions = [".py"]
        self.template_patterns = DjangoConfig().template_patterns
        self.orm_patterns = [
            r"(\w+)\.query\.(all|first|get|filter|count)",
            r"(\w+)\.query\.filter_by\(",
            r"db\.session\.(add|commit|delete|query)",
        ]


class FastAPIConfig(FrameworkConfig):
    framework_name = "fastapi"

    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "BaseModel"},
            {"type": "class_inheritance", "pattern": "SQLModel"},
            {"type": "class_decoration", "pattern": "table"},
        ]
        self.view_patterns = [
            {"type": "function_decorator", "pattern": "@app."},
            {"type": "function_decorator", "pattern": "@router."},
            {"type": "class_decoration", "pattern": "APIRouter"},
        ]
        self.serializer_patterns = [
            {"type": "class_inheritance", "pattern": "BaseModel"},
            {"type": "class_name_suffix", "pattern": "Schema"},
        ]
        self.template_extensions = []
        self.code_extensions = [".py"]
        self.template_patterns = {}
        self.orm_patterns = [
            r"session\.get\((\w+)",
            r"session\.query\((\w+)",
            r"(\w+)\.select\(\)",
            r"session\.execute\(.*select\((\w+)\)",
        ]


FRAMEWORKS = {
    "django": DjangoConfig,
    "flask": FlaskConfig,
    "fastapi": FastAPIConfig,
    "generic": FrameworkConfig,
}

REMOVED_FRAMEWORKS = {
    "rails": "Ruby on Rails support has been removed because FeynMap does not yet include a Ruby parser.",
}

PathLike = Union[str, Path]


def detect_framework(project_path: PathLike) -> FrameworkDetectionResult:
    """Detect the dominant supported framework for a repository."""
    return FrameworkDetector().detect(str(project_path))


def _caller_project_path() -> Optional[PathLike]:
    """Recover the extractor project root for older callers that omit it."""
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame and frame.f_back else None
        owner = caller.f_locals.get("self") if caller else None
        return getattr(owner, "project_path", None)
    finally:
        del frame


def _install_component_metrics() -> None:
    """Install component-level metrics after the parser class is initialized."""
    try:
        from .feyn_parser import FeynExtractor
    except ImportError:
        from feyn_parser import FeynExtractor
    install_component_metric_calculator(FeynExtractor)


def get_framework_config(framework_name="auto", project_path: Optional[PathLike] = None):
    """Return an explicit framework config or auto-detect one from a repository."""
    _install_component_metrics()
    normalized = (framework_name or "auto").lower()
    detection_result: Optional[FrameworkDetectionResult] = None

    if normalized in REMOVED_FRAMEWORKS:
        raise ValueError(REMOVED_FRAMEWORKS[normalized])

    if normalized == "auto":
        detection_root = project_path or _caller_project_path()
        if detection_root is None:
            raise ValueError("project_path is required when framework='auto'")
        detection_result = detect_framework(detection_root)
        normalized = detection_result.framework

    if normalized not in FRAMEWORKS:
        supported = ", ".join(sorted(FRAMEWORKS))
        raise ValueError(f"Unsupported framework '{framework_name}'. Supported values: auto, {supported}")

    config = FRAMEWORKS[normalized]()
    config.detection_result = detection_result
    return config


DEFAULT_CONFIG = DjangoConfig()
