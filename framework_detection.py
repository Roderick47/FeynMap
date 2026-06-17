"""Evidence-based web framework detection for FeynMap."""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class FrameworkDetectionResult:
    framework: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)


class FrameworkDetector:
    """Detect the dominant framework in a repository without importing project code."""

    FRAMEWORKS = ("django", "flask", "fastapi", "rails")
    EXCLUDED_DIRS = {".git", "venv", ".venv", "env", "node_modules", "__pycache__"}

    def detect(self, project_path: str) -> FrameworkDetectionResult:
        root = Path(project_path).resolve()
        scores = {name: 0.0 for name in self.FRAMEWORKS}
        evidence: Dict[str, List[str]] = {name: [] for name in self.FRAMEWORKS}

        files = list(self._iter_files(root))
        relative_paths = {path.relative_to(root).as_posix() for path in files}

        self._score_paths(relative_paths, scores, evidence)
        self._score_python_files(files, root, scores, evidence)
        self._score_dependency_files(files, root, scores, evidence)

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        winner, winner_score = ranked[0]
        runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0

        if winner_score <= 0:
            return FrameworkDetectionResult(
                framework="generic",
                confidence=0.0,
                evidence=["No supported framework evidence was found."],
                scores=scores,
            )

        confidence = self._confidence(winner_score, runner_up_score)
        return FrameworkDetectionResult(
            framework=winner,
            confidence=confidence,
            evidence=evidence[winner],
            scores=scores,
        )

    def _iter_files(self, root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self.EXCLUDED_DIRS for part in path.relative_to(root).parts):
                continue
            yield path

    @staticmethod
    def _add_score(
        framework: str,
        points: float,
        reason: str,
        scores: Dict[str, float],
        evidence: Dict[str, List[str]],
    ) -> None:
        scores[framework] += points
        if reason not in evidence[framework]:
            evidence[framework].append(reason)

    def _score_paths(
        self,
        relative_paths: Set[str],
        scores: Dict[str, float],
        evidence: Dict[str, List[str]],
    ) -> None:
        if "manage.py" in relative_paths:
            self._add_score("django", 8, "manage.py is present", scores, evidence)
        if any(path.endswith("/settings.py") or path == "settings.py" for path in relative_paths):
            self._add_score("django", 3, "Django-style settings.py is present", scores, evidence)
        if any(path.endswith("/urls.py") or path == "urls.py" for path in relative_paths):
            self._add_score("django", 2, "Django-style urls.py is present", scores, evidence)

        if "config/routes.rb" in relative_paths:
            self._add_score("rails", 8, "config/routes.rb is present", scores, evidence)
        if "Gemfile" in relative_paths:
            self._add_score("rails", 2, "Gemfile is present", scores, evidence)
        if any(path.startswith("app/controllers/") for path in relative_paths):
            self._add_score("rails", 4, "app/controllers directory is present", scores, evidence)

    def _score_python_files(
        self,
        files: Iterable[Path],
        root: Path,
        scores: Dict[str, float],
        evidence: Dict[str, List[str]],
    ) -> None:
        for path in files:
            if path.suffix != ".py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue

            relative = path.relative_to(root).as_posix()
            imports = self._python_imports(tree)
            names = self._called_or_assigned_names(tree)
            decorators = self._decorators(tree)

            if any(name == "django" or name.startswith("django.") for name in imports):
                self._add_score("django", 5, f"Django imported in {relative}", scores, evidence)
            if "flask" in imports or any(name.startswith("flask.") for name in imports):
                self._add_score("flask", 5, f"Flask imported in {relative}", scores, evidence)
            if "fastapi" in imports or any(name.startswith("fastapi.") for name in imports):
                self._add_score("fastapi", 5, f"FastAPI imported in {relative}", scores, evidence)

            if "Flask" in names:
                self._add_score("flask", 3, f"Flask application constructed in {relative}", scores, evidence)
            if "FastAPI" in names:
                self._add_score("fastapi", 3, f"FastAPI application constructed in {relative}", scores, evidence)
            if "APIRouter" in names:
                self._add_score("fastapi", 3, f"APIRouter used in {relative}", scores, evidence)

            if any(item.endswith(".route") for item in decorators):
                self._add_score("flask", 2, f"route decorator used in {relative}", scores, evidence)
            if any(
                item.endswith(suffix)
                for item in decorators
                for suffix in (".get", ".post", ".put", ".patch", ".delete")
            ):
                self._add_score("fastapi", 2, f"HTTP method decorator used in {relative}", scores, evidence)

    def _score_dependency_files(
        self,
        files: Iterable[Path],
        root: Path,
        scores: Dict[str, float],
        evidence: Dict[str, List[str]],
    ) -> None:
        dependency_names = {"requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "Gemfile"}
        for path in files:
            if path.name not in dependency_names:
                continue
            try:
                text = path.read_text(encoding="utf-8").lower()
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(root).as_posix()
            if "django" in text:
                self._add_score("django", 4, f"Django dependency found in {relative}", scores, evidence)
            if "fastapi" in text:
                self._add_score("fastapi", 4, f"FastAPI dependency found in {relative}", scores, evidence)
            if "flask" in text:
                self._add_score("flask", 4, f"Flask dependency found in {relative}", scores, evidence)
            if path.name == "Gemfile" and "rails" in text:
                self._add_score("rails", 6, "Rails dependency found in Gemfile", scores, evidence)

    @staticmethod
    def _python_imports(tree: ast.AST) -> Set[str]:
        imports: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        return imports

    @staticmethod
    def _called_or_assigned_names(tree: ast.AST) -> Set[str]:
        names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    names.add(node.func.attr)
        return names

    @staticmethod
    def _decorators(tree: ast.AST) -> Set[str]:
        decorators: Set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for decorator in node.decorator_list:
                try:
                    rendered = ast.unparse(decorator)
                except Exception:
                    continue
                decorators.add(rendered.split("(", 1)[0])
        return decorators

    @staticmethod
    def _confidence(winner_score: float, runner_up_score: float) -> float:
        strength = min(1.0, winner_score / 10.0)
        separation = (winner_score - runner_up_score) / max(winner_score, 1.0)
        return round(max(0.0, min(1.0, (strength * 0.65) + (separation * 0.35))), 2)
