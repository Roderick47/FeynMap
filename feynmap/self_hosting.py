"""Self-hosting benchmark for measuring how well FeynMap understands itself.

Phase 1.6 deliberately treats the FeynMap repository as the first serious
consumer of the semantic engine. The benchmark converts a SemanticGraph into a
small set of architecture-quality metrics and compares the graph with a checked-
in golden specification of facts that should be discoverable.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .core import SemanticGraph, SemanticNode
from .engine import FeynMapEngine


DEFAULT_GOLDEN = Path(__file__).resolve().parent / "data" / "feynmap_golden.json"


def _counter(items: Iterable[str]) -> Dict[str, int]:
    return dict(sorted(Counter(items).items()))


def _selector_matches(node: SemanticNode, selector: str) -> bool:
    value = str(selector or "").casefold()
    if not value:
        return False
    candidates = [node.id, node.name, node.qualified_name or ""]
    folded = [item.casefold() for item in candidates if item]
    return value in folded or any(item.endswith("." + value) for item in folded)


def _select_nodes(graph: SemanticGraph, selector: str) -> List[SemanticNode]:
    exact = [node for node in graph.nodes if _selector_matches(node, selector)]
    if exact:
        return exact
    needle = str(selector or "").casefold()
    return [
        node
        for node in graph.nodes
        if needle and any(needle in value.casefold() for value in (node.id, node.name, node.qualified_name or "") if value)
    ]


def _relationship_present(graph: SemanticGraph, source: str, target: str, kind: str) -> Tuple[bool, List[Dict[str, Any]]]:
    source_nodes = _select_nodes(graph, source)
    target_nodes = _select_nodes(graph, target)
    source_ids = {node.id for node in source_nodes}
    target_ids = {node.id for node in target_nodes}
    matches = [
        edge
        for edge in graph.edges
        if edge.source in source_ids and edge.target in target_ids and edge.kind.value == kind
    ]
    return bool(matches), [edge.to_dict() for edge in matches]


def load_golden(path: Optional[str] = None) -> Dict[str, Any]:
    target = Path(path) if path else DEFAULT_GOLDEN
    return json.loads(target.read_text(encoding="utf-8"))


class SelfAnalysisBenchmark:
    """Score one repository graph against a known architecture specification."""

    def __init__(self, graph: SemanticGraph, golden: Dict[str, Any]) -> None:
        self.graph = graph
        self.golden = golden

    def metrics(self) -> Dict[str, Any]:
        graph = self.graph
        python_unresolved: List[Dict[str, Any]] = []
        unresolved_call_total = 0
        for node in graph.nodes:
            python = node.attributes.get("python", {})
            calls = python.get("unresolved_calls", []) if isinstance(python, dict) else []
            if isinstance(calls, list) and calls:
                unique = sorted({str(item) for item in calls})
                unresolved_call_total += len(unique)
                python_unresolved.append(
                    {
                        "node": node.qualified_name or node.name,
                        "path": node.location.path if node.location else None,
                        "calls": unique,
                    }
                )

        connected_ids = {edge.source for edge in graph.edges} | {edge.target for edge in graph.edges}
        orphan_nodes = [
            node.qualified_name or node.name
            for node in graph.nodes
            if node.id not in connected_ids and node.kind.value not in {"repository", "external_system"}
        ]

        evidence_kinds: List[str] = []
        confidence_tiers: List[str] = []
        for node in graph.nodes:
            evidence_kinds.extend(item.kind.value for item in node.evidence)
            confidence_tiers.append(node.confidence_tier.value)
        for edge in graph.edges:
            evidence_kinds.extend(item.kind.value for item in edge.evidence)
            confidence_tiers.append(edge.confidence_tier.value)

        integration = graph.metadata.get("integration", {})
        if not isinstance(integration, dict):
            integration = {}

        return {
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "languages": _counter(node.language or "unknown" for node in graph.nodes),
            "node_kinds": _counter(node.kind.value for node in graph.nodes),
            "edge_kinds": _counter(edge.kind.value for edge in graph.edges),
            "evidence_kinds": _counter(evidence_kinds),
            "confidence_tiers": _counter(confidence_tiers),
            "evidence_coverage": round(graph.evidence_coverage(), 4),
            "parse_warnings": len(graph.diagnostics.get("warnings", [])),
            "graph_errors": len(graph.diagnostics.get("errors", [])),
            "python_unresolved_call_count": unresolved_call_total,
            "python_nodes_with_unresolved_calls": len(python_unresolved),
            "python_unresolved_sample": python_unresolved[:50],
            "orphan_node_count": len(orphan_nodes),
            "orphan_node_sample": orphan_nodes[:50],
            "integration_resolved_edges": int(integration.get("resolved_edges", 0) or 0),
            "integration_unresolved_contracts": int(integration.get("unresolved_contracts", 0) or 0),
        }

    def evaluate(self) -> Dict[str, Any]:
        symbol_results: List[Dict[str, Any]] = []
        for selector in self.golden.get("expected_symbols", []):
            matches = _select_nodes(self.graph, str(selector))
            symbol_results.append(
                {
                    "selector": selector,
                    "found": bool(matches),
                    "matches": [node.qualified_name or node.id for node in matches[:10]],
                }
            )

        relationship_results: List[Dict[str, Any]] = []
        for expected in self.golden.get("expected_relationships", []):
            source = str(expected.get("source", ""))
            target = str(expected.get("target", ""))
            kind = str(expected.get("kind", ""))
            found, matches = _relationship_present(self.graph, source, target, kind)
            relationship_results.append(
                {
                    "source": source,
                    "target": target,
                    "kind": kind,
                    "found": found,
                    "matches": matches[:5],
                    "importance": expected.get("importance", "critical"),
                    "note": expected.get("note"),
                }
            )

        symbols_found = sum(1 for item in symbol_results if item["found"])
        relationships_found = sum(1 for item in relationship_results if item["found"])
        symbol_score = symbols_found / float(max(len(symbol_results), 1))
        relationship_score = relationships_found / float(max(len(relationship_results), 1))
        evidence_score = self.graph.evidence_coverage()
        architecture_score = (0.4 * symbol_score) + (0.5 * relationship_score) + (0.1 * evidence_score)

        critical_missing = [
            item
            for item in relationship_results
            if not item["found"] and item.get("importance", "critical") == "critical"
        ]
        missing_symbols = [item for item in symbol_results if not item["found"]]

        status = "pass"
        if critical_missing or missing_symbols:
            status = "needs_improvement"
        if self.graph.diagnostics.get("errors"):
            status = "invalid_graph"

        return {
            "status": status,
            "architecture_score": round(architecture_score, 4),
            "symbol_score": round(symbol_score, 4),
            "relationship_score": round(relationship_score, 4),
            "expected_symbol_count": len(symbol_results),
            "expected_relationship_count": len(relationship_results),
            "missing_symbol_count": len(missing_symbols),
            "missing_critical_relationship_count": len(critical_missing),
            "symbols": symbol_results,
            "relationships": relationship_results,
        }

    def quality_gates(
        self,
        metrics: Optional[Dict[str, Any]] = None,
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Evaluate invariant Phase 1.6 release gates without arbitrary thresholds."""
        metrics = metrics or self.metrics()
        evaluation = evaluation or self.evaluate()
        critical_relationships = [
            item
            for item in evaluation.get("relationships", [])
            if item.get("importance", "critical") == "critical"
        ]
        critical_without_evidence = []
        for relationship in critical_relationships:
            if not relationship.get("found"):
                continue
            matches = relationship.get("matches", [])
            if not any(match.get("evidence") for match in matches if isinstance(match, dict)):
                critical_without_evidence.append(
                    {
                        "source": relationship.get("source"),
                        "target": relationship.get("target"),
                        "kind": relationship.get("kind"),
                    }
                )

        gates = [
            {
                "id": "golden-symbols-present",
                "passed": evaluation.get("missing_symbol_count", 0) == 0,
                "detail": "Every golden architecture symbol must be present.",
            },
            {
                "id": "critical-relationships-present",
                "passed": evaluation.get("missing_critical_relationship_count", 0) == 0,
                "detail": "Every critical golden architecture relationship must be resolved.",
            },
            {
                "id": "graph-valid",
                "passed": metrics.get("graph_errors", 0) == 0,
                "detail": "Semantic graph validation must report zero errors.",
            },
            {
                "id": "critical-relationships-evidenced",
                "passed": not critical_without_evidence,
                "detail": "Every resolved critical golden relationship must carry evidence.",
            },
        ]
        failed = [gate for gate in gates if not gate["passed"]]
        return {
            "status": "pass" if not failed else "fail",
            "gate_count": len(gates),
            "passed_gate_count": len(gates) - len(failed),
            "failed_gate_count": len(failed),
            "gates": gates,
            "critical_relationships_without_evidence": critical_without_evidence,
            "deferred_numeric_thresholds": [
                "python_unresolved_call_count",
                "evidence_coverage",
                "orphan_node_count",
                "integration_unresolved_contracts",
            ],
        }

    def report(self) -> Dict[str, Any]:
        metrics = self.metrics()
        evaluation = self.evaluate()
        return {
            "benchmark": {
                "name": self.golden.get("name", "FeynMap self-analysis"),
                "version": self.golden.get("benchmark_version", "1.0"),
                "repository": self.golden.get("repository"),
                "baseline_commit": self.golden.get("baseline_commit"),
                "baseline_version": self.golden.get("baseline_version"),
            },
            "metrics": metrics,
            "evaluation": evaluation,
            "quality_gates": self.quality_gates(metrics, evaluation),
            "known_blind_spots": self.golden.get("known_blind_spots", []),
        }


def run_self_analysis(
    project_path: str = ".",
    golden_path: Optional[str] = None,
    language: str = "auto",
    framework: str = "auto",
) -> Dict[str, Any]:
    """Analyze a repository and evaluate it as a FeynMap self-hosting benchmark."""
    graph = FeynMapEngine().analyze(project_path, language=language, framework=framework)
    return SelfAnalysisBenchmark(graph, load_golden(golden_path)).report()
