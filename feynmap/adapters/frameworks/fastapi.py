"""FastAPI semantic enrichment for generic Python graphs."""
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
    route_method_decorator,
)


class FastAPIAdapter(FrameworkAdapter):
    name = "fastapi"
    language = "python"

    def detect_score(self, project_path: Path) -> float:
        score = 0.0
        if "fastapi" in dependency_text(project_path):
            score += 0.35
        imports = repository_imports(project_path)
        if imported(imports, "fastapi"):
            score += 0.55
        if imported(imports, "sqlmodel"):
            score += 0.05
        return min(1.0, score)

    def enrich(self, graph: SemanticGraph, project_path: Path) -> SemanticGraph:
        file_imports = imports_by_file(project_path)
        for node in graph.nodes:
            if node.language != "python":
                continue
            imports = node_imports(node, file_imports)

            if node.kind == NodeKind.FUNCTION and route_method_decorator(node) and imported(imports, "fastapi"):
                mark_role(node, self.name, NodeKind.HANDLER, "request_handler", "FastAPI route decorator detected")
            elif node.kind == NodeKind.CLASS:
                if has_base(node, "SQLModel") and imported(imports, "sqlmodel"):
                    mark_role(node, self.name, NodeKind.DATA_MODEL, "persistent_model", "SQLModel table/domain model detected", 0.96)
                elif has_base(node, "BaseModel") and imported(imports, "pydantic"):
                    mark_role(node, self.name, NodeKind.TRANSFORMER, "schema", "Pydantic model used as FastAPI schema", 0.94)

        attach_decorator_http_contracts(graph, self.name)
        attach_template_render_contracts(graph, project_path, self.name)
        return finalize(graph, self.name)
