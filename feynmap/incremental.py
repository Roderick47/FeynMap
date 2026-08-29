"""Conservative incremental repository analysis over stored FeynMap snapshots.

Incremental analysis is an optimization layer, not a new source of truth. It uses
repository file fingerprints to decide whether a previous snapshot can be reused,
and falls back to a full FeynMapEngine analysis whenever correctness cannot be
proved from the available static dependency evidence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .core import EdgeKind, SemanticGraph, SemanticNode
from .diff import diff_file_inventories
from .engine import ANALYSIS_CONTRACT_VERSION, FeynMapEngine
from .snapshots import (
    RepositorySnapshot,
    SnapshotStore,
    capture_repository_snapshot,
    repository_file_inventory,
    repository_locator,
)


@dataclass
class IncrementalPlan:
    mode: str
    reason: str
    changed_files: List[str] = field(default_factory=list)
    impacted_files: List[str] = field(default_factory=list)
    reused_files: List[str] = field(default_factory=list)
    fallback: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "changed_files": list(self.changed_files),
            "impacted_files": list(self.impacted_files),
            "reused_files": list(self.reused_files),
            "fallback": self.fallback,
        }


def _node_source_path(node: SemanticNode) -> Optional[str]:
    if node.location and node.location.path:
        return node.location.path
    for namespace in ("python", "javascript", "html"):
        payload = node.attributes.get(namespace)
        if isinstance(payload, dict):
            raw = payload.get("path")
            if isinstance(raw, str) and raw:
                return raw
    return None


def _file_nodes(graph: SemanticGraph) -> Dict[str, Set[str]]:
    result: Dict[str, Set[str]] = {}
    for node in graph.nodes:
        path = _node_source_path(node)
        if path:
            result.setdefault(path, set()).add(node.id)
    return result


def _dependency_closure(graph: SemanticGraph, changed_files: Iterable[str]) -> Set[str]:
    """Return a conservative file-level invalidation closure.

    Any file containing a node directly changed is invalidated. Files containing
    nodes that import, call, extend, depend on, render/load/invoke, route/request,
    or otherwise connect to an invalidated node are recursively invalidated too.
    This intentionally favors correctness over minimum work.
    """
    file_nodes = _file_nodes(graph)
    node_to_file: Dict[str, str] = {}
    for path, node_ids in file_nodes.items():
        for node_id in node_ids:
            node_to_file[node_id] = path

    impacted_files: Set[str] = set(changed_files)
    impacted_nodes: Set[str] = set()
    for path in list(impacted_files):
        impacted_nodes.update(file_nodes.get(path, set()))

    propagating_kinds = {
        EdgeKind.IMPORTS,
        EdgeKind.CALLS,
        EdgeKind.DEPENDS_ON,
        EdgeKind.EXTENDS,
        EdgeKind.IMPLEMENTS,
        EdgeKind.LOADS,
        EdgeKind.RENDERS,
        EdgeKind.INVOKES,
        EdgeKind.SPAWNS,
        EdgeKind.REQUESTS,
        EdgeKind.CONNECTS_TO,
        EdgeKind.ROUTES_TO,
        EdgeKind.FLOWS_TO,
        EdgeKind.USES_DATA,
        EdgeKind.READS,
        EdgeKind.WRITES,
        EdgeKind.MUTATES,
        EdgeKind.PERSISTS,
        EdgeKind.EMITS,
        EdgeKind.SUBSCRIBES,
    }

    changed = True
    while changed:
        changed = False
        for edge in graph.edges:
            if edge.kind not in propagating_kinds:
                continue
            if edge.target not in impacted_nodes:
                continue
            source_file = node_to_file.get(edge.source)
            if not source_file or source_file in impacted_files:
                continue
            impacted_files.add(source_file)
            impacted_nodes.update(file_nodes.get(source_file, set()))
            changed = True
    return impacted_files


def _inventory_snapshot(project_path: Path, previous: RepositorySnapshot) -> RepositorySnapshot:
    files = repository_file_inventory(project_path)
    return RepositorySnapshot(
        snapshot_id="inventory-only",
        repository_key=previous.repository_key,
        locator=previous.locator,
        root_hint=str(project_path.resolve()),
        revision=previous.revision,
        content_hash="inventory-only",
        graph_hash=previous.graph_hash,
        graph_schema_version=previous.graph_schema_version,
        analysis_options=dict(previous.analysis_options),
        files=files,
        created_at=previous.created_at,
    )


def _repository_key(project_path: Path) -> str:
    locator = repository_locator(project_path)
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()


def plan_incremental_analysis(
    project_path: Path,
    previous_snapshot: RepositorySnapshot,
    previous_graph: SemanticGraph,
    analysis_options: Optional[Dict[str, object]] = None,
) -> IncrementalPlan:
    """Plan a safe incremental step from a previous stored snapshot."""
    root = project_path.resolve()
    current_paths = {item.path for item in repository_file_inventory(root)}
    previous_paths = {item.path for item in previous_snapshot.files}

    if _repository_key(root) != previous_snapshot.repository_key:
        return IncrementalPlan(
            mode="full_rebuild",
            reason="previous snapshot belongs to a different repository identity",
            changed_files=sorted(previous_paths | current_paths),
            impacted_files=sorted(previous_paths | current_paths),
            reused_files=[],
            fallback=True,
        )

    previous_contract = previous_graph.metadata.get("analysis_contract_version")
    if previous_contract != ANALYSIS_CONTRACT_VERSION:
        return IncrementalPlan(
            mode="full_rebuild",
            reason="analysis contract changed or is missing from the previous snapshot",
            changed_files=[],
            impacted_files=sorted(current_paths),
            reused_files=[],
            fallback=True,
        )

    requested_options = dict(analysis_options or previous_snapshot.analysis_options)
    if requested_options != dict(previous_snapshot.analysis_options):
        return IncrementalPlan(
            mode="full_rebuild",
            reason="analysis options differ from the previous snapshot",
            changed_files=[],
            impacted_files=sorted(current_paths),
            reused_files=[],
            fallback=True,
        )

    current_inventory = _inventory_snapshot(root, previous_snapshot)
    file_delta = diff_file_inventories(previous_snapshot, current_inventory)
    changed_files = sorted(
        set(file_delta["added"]) | set(file_delta["removed"]) | set(file_delta["modified"])
    )
    if not changed_files:
        return IncrementalPlan(
            mode="reuse",
            reason="repository inventory, analysis options, and analysis contract are unchanged",
            changed_files=[],
            impacted_files=[],
            reused_files=sorted(item.path for item in previous_snapshot.files),
            fallback=False,
        )

    removed = set(file_delta["removed"])
    added = set(file_delta["added"])
    if added or removed:
        return IncrementalPlan(
            mode="full_rebuild",
            reason="added or removed files can change repository topology/detection",
            changed_files=changed_files,
            impacted_files=sorted(previous_paths | current_paths),
            reused_files=[],
            fallback=True,
        )

    impacted = _dependency_closure(previous_graph, changed_files)
    reusable = sorted(current_paths - impacted)
    return IncrementalPlan(
        mode="partial_candidate",
        reason="modified files have a conservative dependency closure; adapter partial-parse merge is not yet proven",
        changed_files=changed_files,
        impacted_files=sorted(impacted),
        reused_files=reusable,
        fallback=True,
    )


def analyze_incrementally(
    project_path: Path,
    previous_snapshot: RepositorySnapshot,
    previous_graph: SemanticGraph,
    language: str = "auto",
    framework: str = "auto",
    engine: Optional[FeynMapEngine] = None,
) -> Tuple[SemanticGraph, IncrementalPlan]:
    """Return a correct graph while recording what could safely be reused.

    Phase 2A deliberately does not splice adapter subgraphs yet. When files are
    unchanged the previous graph is reused exactly. When anything changed, the
    planner exposes the invalidation closure but a full rebuild remains the
    correctness fallback until adapters expose deterministic per-file fragments.
    """
    options = {"language_selection": language, "framework_selection": framework}
    plan = plan_incremental_analysis(
        project_path,
        previous_snapshot,
        previous_graph,
        analysis_options=options,
    )
    if plan.mode == "reuse":
        return previous_graph, plan
    analyzer = engine or FeynMapEngine()
    graph = analyzer.analyze(str(project_path), language=language, framework=framework)
    return graph, plan


def incremental_snapshot(
    project_path: Path,
    store: SnapshotStore,
    previous_snapshot_id: str,
    language: str = "auto",
    framework: str = "auto",
) -> Tuple[RepositorySnapshot, SemanticGraph, IncrementalPlan]:
    previous_snapshot, previous_graph = store.load(previous_snapshot_id)
    graph, plan = analyze_incrementally(
        project_path,
        previous_snapshot,
        previous_graph,
        language=language,
        framework=framework,
    )
    snapshot = capture_repository_snapshot(
        project_path,
        graph,
        analysis_options={"language_selection": language, "framework_selection": framework},
    )
    store.save(snapshot, graph, set_current=True)
    return snapshot, graph, plan
