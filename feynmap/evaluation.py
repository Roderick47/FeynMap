"""Language-neutral evaluation against explicitly annotated graph relationships.

Unlabeled relationships are unjudged, never implicitly false. Selectors are
exact and must be unique; no language syntax or adapter implementation is used.
"""
from collections import Counter, defaultdict
from typing import Any, Dict

from .core import EdgeKind, SemanticGraph
from .core.model import TIER_RANK
from .core.ontology import CONFIDENCE_POLICY_VERSION

BENCHMARK_SCHEMA = "feynmap.relationship_benchmark.v1"


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def evaluate_graph(graph: SemanticGraph, annotations: Dict[str, Any]) -> Dict[str, Any]:
    """Measure only explicitly labeled pairs; undefined metrics are null."""
    if not isinstance(annotations, dict) or annotations.get('schema') != BENCHMARK_SCHEMA:
        raise ValueError('unsupported benchmark schema')
    if set(annotations) - {'schema', 'name', 'symbols', 'relationships'}:
        raise ValueError('unknown benchmark fields')
    symbols = annotations.get('symbols')
    labels = annotations.get('relationships')
    if not isinstance(symbols, dict) or not symbols or not isinstance(labels, list) or not labels:
        raise ValueError('non-empty symbols and relationships are required')
    ids = {node.id for node in graph.nodes}
    if len(ids) != len(graph.nodes) or len({edge.id for edge in graph.edges}) != len(graph.edges):
        raise ValueError('graph has duplicate identities')
    if any(edge.source not in ids or edge.target not in ids for edge in graph.edges):
        raise ValueError('graph has dangling relationships')

    resolved = {}
    missing = []
    for alias, selector in sorted(symbols.items()):
        if not isinstance(alias, str) or not alias or not isinstance(selector, dict):
            raise ValueError('symbols require named object selectors')
        if (set(selector) - {'id', 'name', 'qualified_name', 'language', 'path'}
                or not set(selector) & {'id', 'name', 'qualified_name'}
                or any(not isinstance(value, str) or not value for value in selector.values())):
            raise ValueError('invalid exact selector: %s' % alias)
        matches = []
        for node in graph.nodes:
            values = {'id': node.id, 'name': node.name, 'qualified_name': node.qualified_name,
                      'language': node.language, 'path': node.location.path if node.location else None}
            if all(values[key] == value for key, value in selector.items()):
                matches.append(node.id)
        if len(matches) > 1:
            raise ValueError('ambiguous benchmark selector: %s' % alias)
        resolved[alias] = matches[0] if matches else None
        if not matches:
            missing.append(alias)

    edge_index = defaultdict(list)
    for edge in graph.edges:
        edge_index[(edge.source, edge.kind.value, edge.target)].append(edge)
    seen = set()
    judged_keys = set()
    counts = Counter()
    tier_counts = defaultdict(Counter)
    language_counts = defaultdict(Counter)
    results = []
    for label in labels:
        if not isinstance(label, dict) or set(label) != {'source', 'target', 'kind', 'present'}:
            raise ValueError('relationship requires source, target, kind, present')
        source, target, kind, present = (label[key] for key in ('source', 'target', 'kind', 'present'))
        if not all(isinstance(value, str) for value in (source, target, kind)):
            raise ValueError('relationship names must be strings')
        if source not in symbols or target not in symbols or type(present) is not bool:
            raise ValueError('unknown symbol or non-boolean present label')
        EdgeKind(kind)  # Reject misspelled relation types instead of scoring them.
        key = (resolved[source], kind, resolved[target])
        # Also reject repeated labels through different aliases for the same nodes.
        identity = (resolved[source] or ('missing', source), kind, resolved[target] or ('missing', target))
        if identity in seen:
            raise ValueError('duplicate or contradictory relationship label')
        seen.add(identity)
        endpoints_present = key[0] is not None and key[2] is not None
        edges = edge_index.get(key, []) if endpoints_present else []
        if endpoints_present:
            judged_keys.add(key)
        if present:
            outcome = 'true_positive' if edges else 'false_negative'
        elif not endpoints_present:
            outcome = 'unscorable_negative'
        else:
            outcome = 'false_positive' if edges else 'true_negative'
        counts[outcome] += 1
        tier = None
        if edges:
            strongest = max(edges, key=lambda edge: TIER_RANK[edge.confidence_tier])
            tier = strongest.confidence_tier.value
            tier_counts[tier]['correct' if present else 'incorrect'] += 1
        languages = tuple(
            graph.node(resolved[alias]).language or 'unknown' if resolved[alias] else symbols[alias].get('language', 'unknown')
            for alias in (source, target)
        )
        language_counts[languages][outcome] += 1
        results.append({**label, 'outcome': outcome, 'confidence_tier': tier,
                        'matching_edge_ids': sorted(edge.id for edge in edges)})

    def metrics(c):
        tp, fp, fn = c['true_positive'], c['false_positive'], c['false_negative']
        return {**{key: c[key] for key in ('true_positive', 'false_positive', 'false_negative',
                                         'true_negative', 'unscorable_negative')},
                'labeled_precision': _ratio(tp, tp + fp), 'labeled_recall': _ratio(tp, tp + fn)}

    return {
        'schema': BENCHMARK_SCHEMA, 'name': annotations.get('name', ''),
        'confidence_policy': CONFIDENCE_POLICY_VERSION,
        'status': 'needs_improvement' if missing or counts['false_positive'] or counts['false_negative'] else 'pass',
        'scope': 'Only annotated pairs are scored. Unjudged edges are not false positives; results are not repository-wide accuracy.',
        'metrics': metrics(counts), 'missing_symbols': missing,
        'unjudged_relationships': len(set(edge_index) - judged_keys),
        'tier_observations': {
            tier: {'correct': c['correct'], 'incorrect': c['incorrect'],
                   'sample_size': c['correct'] + c['incorrect'],
                   'labeled_precision': _ratio(c['correct'], c['correct'] + c['incorrect'])}
            for tier, c in sorted(tier_counts.items())
        },
        'language_pairs': [{'source_language': pair[0], 'target_language': pair[1], **metrics(c)}
                           for pair, c in sorted(language_counts.items())],
        'relationships': sorted(results, key=lambda item: (item['source'], item['kind'], item['target'])),
    }
