"""Django semantic enrichment for generic Python graphs."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from ..base import FrameworkAdapter
from ._python import (
    attach_django_url_contracts,
    attach_template_render_contracts,
    dependency_text,
    finalize,
    has_base,
    imported,
    imports_by_file,
    iter_python_files,
    mark_role,
    node_imports,
    repository_imports,
)


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
        if any(path.name == "settings.py" for path in iter_python_files(project_path)):
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

        self._attach_app_config_relationships(graph)
        attach_django_url_contracts(graph, project_path)
        attach_template_render_contracts(graph, project_path, self.name)
        return finalize(graph, self.name)

    @staticmethod
    def _app_root(path: str) -> str:
        parent = PurePosixPath(path).parent.as_posix()
        return "" if parent == "." else parent

    @classmethod
    def _attach_app_config_relationships(cls, graph: SemanticGraph) -> None:
        """Connect Django request handlers to their nearest AppConfig.

        Django initializes an installed app through AppConfig before its request
        handlers participate in the application. The relationship is structural
        framework wiring rather than a Python call, so model it explicitly.
        """
        configs: List[SemanticNode] = []
        for node in graph.nodes:
            if (
                node.language == "python"
                and node.kind == NodeKind.CLASS
                and node.location
                and node.location.path.endswith("apps.py")
                and has_base(node, "AppConfig")
            ):
                mark_role(
                    node,
                    "django",
                    NodeKind.SERVICE,
                    "app_configuration",
                    "Django AppConfig lifecycle class detected",
                    0.96,
                )
                configs.append(node)
        if not configs:
            return

        configs.sort(
            key=lambda node: (
                -len(cls._app_root(node.location.path).split("/")),
                node.id,
            )
        )
        edge_keys = {(edge.source, edge.target, edge.kind.value) for edge in graph.edges}
        for node in graph.nodes:
            if node.language != "python" or node.kind != NodeKind.HANDLER or not node.location:
                continue
            handler_path = node.location.path
            matches: List[SemanticNode] = []
            for config in configs:
                app_root = cls._app_root(config.location.path)
                if not app_root:
                    if "/" not in handler_path:
                        matches.append(config)
                    continue
                if handler_path == app_root or handler_path.startswith(app_root + "/"):
                    matches.append(config)
            if not matches:
                continue
            config = matches[0]
            key = (node.id, config.id, EdgeKind.DEPENDS_ON.value)
            if key in edge_keys:
                continue
            raw = "%s|%s|django_app_config" % (node.id, config.id)
            graph.add_edge(
                SemanticEdge(
                    id="edge:framework:%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
                    source=node.id,
                    target=config.id,
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.86,
                    evidence=[
                        Evidence(
                            EvidenceKind.FRAMEWORK,
                            "django.app_config",
                            "Django handler belongs to app initialized by AppConfig",
                            node.location,
                            0.86,
                        )
                    ],
                    attributes={
                        "framework": {
                            "name": "django",
                            "relationship": "app_config",
                        }
                    },
                )
            )
            edge_keys.add(key)
