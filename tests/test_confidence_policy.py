import math
import pytest
from feynmap.core import Evidence, EvidenceKind, EdgeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.query import FeynMapQuery


@pytest.mark.parametrize('kind,expected', [
    (EvidenceKind.STATIC, 'supported'), (EvidenceKind.FRAMEWORK, 'supported'),
    (EvidenceKind.INTEGRATION, 'supported'), (EvidenceKind.HEURISTIC, 'inferred'),
    (EvidenceKind.AI_INFERENCE, 'inferred'), (EvidenceKind.HISTORY, 'inferred'),
    (EvidenceKind.RUNTIME, 'verified'), (EvidenceKind.TEST, 'verified'),
])
def test_evidence_kind_caps_high_scores(kind, expected):
    evidence = [Evidence(kind, 'fixture', confidence=1)]
    assert SemanticNode('n', 'n', evidence=evidence).confidence_tier.value == expected
    assert SemanticEdge('e', 'a', 'b', EdgeKind.CALLS, 1, evidence).confidence_tier.value == expected


def test_weak_observation_cannot_borrow_strong_heuristic_score():
    evidence = [Evidence(EvidenceKind.RUNTIME, 'trace', confidence=.2),
                Evidence(EvidenceKind.HEURISTIC, 'guess', confidence=1)]
    node = SemanticNode('n', 'n', evidence=evidence)
    assert node.confidence_tier.value == 'inferred'
    node.evidence.append(Evidence(EvidenceKind.STATIC, 'ast', confidence=.9))
    assert node.confidence_tier.value == 'supported'


@pytest.mark.parametrize('score', [math.nan, math.inf, -1, 2])
def test_invalid_edge_scores_remain_unknown(score):
    edge = SemanticEdge('e', 'a', 'b', EdgeKind.CALLS, score,
                        [Evidence(EvidenceKind.RUNTIME, 'trace', confidence=1)])
    assert edge.confidence_tier.value == 'unknown'


def test_edge_evidence_score_caps_claim_and_no_evidence_is_unknown():
    edge = SemanticEdge('e', 'a', 'b', EdgeKind.CALLS, 1,
                        [Evidence(EvidenceKind.STATIC, 'ast', confidence=.2)])
    assert edge.confidence_tier.value == 'unknown'
    edge.evidence = []
    assert edge.confidence_tier.value == 'unknown'


def test_claim_separates_evidence_existence_from_support():
    edge = SemanticEdge('e', 'a', 'b', EdgeKind.CALLS, 1,
                        [Evidence(EvidenceKind.AI_INFERENCE, 'llm', confidence=1)])
    graph = SemanticGraph([SemanticNode('a', 'a'), SemanticNode('b', 'b')], [edge])
    claim = FeynMapQuery(graph).validate_claim('a', 'b')
    assert claim['evidence_found'] and not claim['supported']
    assert claim['status'] == 'inferred'
    graph.add_edge(SemanticEdge('e2', 'a', 'b', EdgeKind.CALLS, .9,
                               [Evidence(EvidenceKind.STATIC, 'ast', confidence=.9)]))
    assert FeynMapQuery(graph).validate_claim('a', 'b')['status'] == 'supported'


def test_legacy_javascript_scanner_evidence_is_inferred():
    evidence = Evidence(EvidenceKind.STATIC, 'javascript.source.call', confidence=1)
    assert SemanticNode('n', 'n', evidence=[evidence]).confidence_tier.value == 'inferred'
