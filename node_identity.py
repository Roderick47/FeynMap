"""Canonical, globally unique identities for FeynMap graph nodes."""

from pathlib import Path
from typing import Optional


class NodeIdentity:
    """Build stable node IDs relative to a repository root."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def relative_path(self, path: Path | str) -> str:
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.project_root).as_posix()
        except ValueError:
            return resolved.as_posix()

    def module_name(self, path: Path | str) -> str:
        relative = Path(self.relative_path(path))
        without_suffix = relative.with_suffix("")
        parts = list(without_suffix.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts) or "__root__"

    def python(self, name: str, path: Path | str, parent: Optional[str] = None) -> str:
        module = self.module_name(path)
        qualified = f"{parent}.{name}" if parent else name
        return f"python:{module}.{qualified}"

    def template(self, path: Path | str) -> str:
        return f"template:{self.relative_path(path)}"

    def template_symbol(self, path: Path | str, name: str) -> str:
        return f"template-symbol:{self.relative_path(path)}::{name}"

    def javascript(self, path: Path | str, name: str) -> str:
        return f"javascript:{self.relative_path(path)}::{name}"

    @staticmethod
    def ajax(endpoint: str) -> str:
        return f"ajax:{endpoint}"

    @staticmethod
    def dependency(name: str) -> str:
        return f"dependency:{name}"

    @staticmethod
    def unresolved(kind: str, name: str) -> str:
        return f"unresolved:{kind}:{name}"
