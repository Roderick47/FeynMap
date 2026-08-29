"""Django semantic enrichment for generic Python graphs."""
from __future__ import annotations

from pathlib import Path

from feynmap.core import NodeKind, SemanticGraph
from ..base import FrameworkAdapter
from ._python import dependency_text, finalize, has_base, imported, imports_by_file, mark_role, node_imports, repository_imports


class DjangoAdapter(FrameworkAdapter):
    name = "django"
    language = "python"

    def detect_score(self, project_path: Path) -> float:
        score = 0.0
        if (project_path / "manage.py").exists():
            score += 0.45
        if "django" in dependency_text(project_path):
            score += 0.25
        imports = repository_imports(project_path)
        if imported(imports, "django"):
            score += 0.35
        if any(path.name == "settings.py" for path in project_path.rglob("settings.py")):
            score += 0.1
        return min(1.0, score)

    def enrich(self, graph: SemanticGraph, project_path: Path) -> SemanticGraph:
        file_imports = imports_by_file(project_path)
        for node in graph.nodes:
            if node.language != "python":
                continue
            imports = node_imports(node, file_imports)
            path = node.location.path if node.location else ""
            python = node.attributes.get("python", {})

            if node.kind == NodeKind.CLASS:
                bases = python.get("bases", []) if isinstance(python, dict) else []
                if has_base(node, "Model") and (imported(imports, "django.db") or any(str(base).endswith("models.Model") for base in bases)):
                    mark_role(node, self.name, NodeKind.DATA_MODEL, "persistent_model", "Django model inheritance detected")
                elif has_base(node, "Serializer", "ModelSerializer", "HyperlinkedModelSerializer") and imported(imports, "rest_framework"):
                    mark_role(node, self.name, NodeKind.TRANSFORMER, "serializer", "Django REST Framework serializer inheritance detected")
                elif has_base(node, "MiddlewareMixin") or path.endswith("middleware.py"):
                    mark_role(node, self.name, NodeKind.MIDDLEWARE, "middleware", "Django middleware convention detected", 0.9)
                elif has_base(node, "View", "APIView", "ViewSet", "ModelViewSet", "GenericAPIView", "TemplateView", "ListView", "DetailView", "CreateView", "UpdateView", "DeleteView"):
                    mark_role(node, self.name, NodeKind.HANDLER, "request_handler", "Django/DRF view inheritance detected")
            elif node.kind == NodeKind.FUNCTION and (path.endswith("views.py") or "/views/" in path):
                mark_role(node, self.name, NodeKind.HANDLER, "request_handler", "Function defined in a Django views module", 0.82)

        return finalize(graph, self.name)
