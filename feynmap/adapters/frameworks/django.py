"""Django semantic enrichment for generic Python graphs."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from feynmap.core import Evidence, EvidenceKind, NodeKind, SemanticGraph, SemanticNode
from ..base import FrameworkAdapter
from .django_cbv import enrich_django_cbvs
from .django_urls import enrich_django_named_urls
from ._python import (
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

        # P1.2: resolve real CBV class-body source facts before graph merging.
        # The existing language-neutral integration resolver later attaches
        # template contracts to actual HTML nodes, where present.
        enrich_django_cbvs(graph, project_path)
        self._record_app_config_membership(graph)
        enrich_django_named_urls(graph, project_path)
        attach_template_render_contracts(graph, project_path, self.name)
        return finalize(graph, self.name)

    @staticmethod
    def _app_root(path: str) -> str:
        parent = PurePosixPath(path).parent.as_posix()
        return "" if parent == "." else parent

    @classmethod
    def _record_app_config_membership(cls, graph: SemanticGraph) -> None:
        """Record source-tree membership, NOT an application dependency edge.

        A sibling apps.py AppConfig suggests a source-code app boundary. It
        does not prove the app is installed, the handler is called by that
        config, or a change to the config behaviorally impacts all handlers.

        Keep these structural observations in graph metadata, outside generic
        edge traversal, region adjacency and claim validation. Preserve source
        provenance for explicit inspection and snapshot round-trips.
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
                    node, "django", NodeKind.SERVICE, "app_configuration",
                    "Django AppConfig class detected in apps.py", 0.96,
                )
                configs.append(node)

        associations: List[Dict[str, object]] = []
        unresolved: List[Dict[str, object]] = []
        for handler in sorted(graph.nodes, key=lambda node: node.id):
            if (
                handler.language != "python"
                or handler.kind != NodeKind.HANDLER
                or not handler.location
            ):
                continue
            handler_path = handler.location.path
            matches = []
            for config in configs:
                root = cls._app_root(config.location.path)
                if (
                    (not root and "/" not in handler_path)
                    or (root and handler_path.startswith(root + "/"))
                ):
                    matches.append((len(PurePosixPath(root).parts), config, root))
            if not matches:
                continue
            nearest_depth = max(depth for depth, _, _ in matches)
            nearest = sorted(
                ((config, root) for depth, config, root in matches
                 if depth == nearest_depth),
                key=lambda item: item[0].id,
            )
            if len(nearest) != 1:
                unresolved.append({
                    "handler_node_id": handler.id,
                    "reason": "ambiguous_nearest_app_config",
                    "candidate_config_node_ids": [config.id for config, _ in nearest],
                })
                continue
            config, root = nearest[0]
            evidence = Evidence(
                EvidenceKind.FRAMEWORK,
                "django.app_config.source_tree_membership",
                "Handler and AppConfig share nearest source directory; "
                "runtime installation or behavioral dependence is not established",
                handler.location,
                0.65,
            )
            associations.append({
                "handler_node_id": handler.id,
                "app_config_node_id": config.id,
                "app_root": root,
                "handler_source_path": handler_path,
                "app_config_source_path": config.location.path,
                "scope": "source_tree_only",
                "confidence_tier": "inferred",
                "evidence": evidence.to_dict(),
            })

        graph.metadata["django_app_membership"] = {
            "version": "1.0.0",
            "relationship": "source_tree_membership_not_behavioral_dependency",
            "associations": associations,
            "unresolved": unresolved,
        }


def django_app_memberships(graph: SemanticGraph, handler_node_id: Optional[str] = None) -> List[Dict[str, object]]:
    """Read inferred structural membership without traversing behavioral edges."""
    payload = graph.metadata.get("django_app_membership") or {}
    entries = payload.get("associations", []) if isinstance(payload, dict) else []
    return [
        item for item in entries
        if isinstance(item, dict)
        and (handler_node_id is None or item.get("handler_node_id") == handler_node_id)
    ]
