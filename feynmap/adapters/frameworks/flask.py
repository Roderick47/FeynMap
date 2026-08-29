"""Flask semantic enrichment for generic Python graphs."""
from __future__ import annotations

from pathlib import Path

from feynmap.core import NodeKind, SemanticGraph
from ..base import FrameworkAdapter
from ._python import (
    attach_decorator_http_contracts,
    attach_template_render_contracts,
    dependency_text,
    finalize,
    has_base,
    imported,
    imports_by_file,
    mark_role,
    node_imports,
    repository_imports,
)


class FlaskAdapter(FrameworkAdapter):
    name = "flask"
    language = "python"

    def detect_score(self, project_path: Path) -> float:
        score = 0.0
        if "flask" in dependency_text(project_path):
            score += 0.35
        imports = repository_imports(project_path)
        if imported(imports, "flask"):
            score += 0.5
        if imported(imports, "flask_sqlalchemy"):
            score += 0.1
        return min(1.0, score)

    def enrich(self, graph: SemanticGraph, project_path: Path) -> SemanticGraph:
        file_imports = imports_by_file(project_path)
        for node in graph.nodes:
            if node.language != "python":
                continue
            imports = node_imports(node, file_imports)
            python = node.attributes.get("python", {})
            decorators = python.get("decorators", []) if isinstance(python, dict) else []
            bases = python.get("bases", []) if isinstance(python, dict) else []

            if node.kind == NodeKind.FUNCTION and any(str(item).split("(", 1)[0].endswith(".route") for item in decorators):
                mark_role(node, self.name, NodeKind.HANDLER, "request_handler", "Flask route decorator detected")
            elif node.kind == NodeKind.CLASS:
                if any(str(base).endswith("db.Model") for base in bases) or (has_base(node, "Model") and imported(imports, "flask_sqlalchemy")):
                    mark_role(node, self.name, NodeKind.DATA_MODEL, "persistent_model", "Flask-SQLAlchemy model inheritance detected")
                elif has_base(node, "Schema") and (imported(imports, "marshmallow") or imported(imports, "flask_marshmallow")):
                    mark_role(node, self.name, NodeKind.TRANSFORMER, "serializer", "Marshmallow schema used by Flask application", 0.94)

        attach_decorator_http_contracts(graph, self.name)
        attach_template_render_contracts(graph, project_path, self.name)
        return finalize(graph, self.name)
