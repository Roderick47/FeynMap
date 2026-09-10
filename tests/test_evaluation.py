import copy
import json
from pathlib import Path
import pytest
from feynmap import FeynMapEngine, evaluate_graph
from feynmap.core import SemanticGraph, SemanticNode, SemanticEdge, EdgeKind, Evidence, EvidenceKind
from feynmap.evaluation import BENCHMARK_SCHEMA
from feynmap.cli import main

FIXTURE = Path(__file__).parent / 'fixtures' / 'benchmark_mixed'


def sample():
    graph = SemanticGraph([
        SemanticNode('a', 'same', language='future-language'),
        SemanticNode('b', 'same', language='other-language'),
        SemanticNode('c', 'third', language='other-language'),
    ], [SemanticEdge('ab', 'a', 'b', EdgeKind.CALLS, .9,
                     [Evidence(EvidenceKind.STATIC, 'fixture', confidence=.9)])])
    labels = {'schema': BENCHMARK_SCHEMA,
              'symbols': {key: {'id': key} for key in 'abc'},
              'relationships': [
                  {'source': 'a', 'target': 'b', 'kind': 'calls', 'present': True},
                  {'source': 'a', 'target': 'c', 'kind': 'calls', 'present': True},
                  {'source': 'b', 'target': 'a', 'kind': 'calls', 'present': False}]}
    return graph, labels


def test_metrics_are_labeled_only_and_language_neutral():
    graph, labels = sample()
    graph.add_edge(SemanticEdge('ba', 'b', 'a', EdgeKind.CALLS, .9))
    graph.add_edge(SemanticEdge('bc', 'b', 'c', EdgeKind.IMPORTS, .9))
    report = evaluate_graph(graph, labels)
    assert report['metrics']['labeled_precision'] == .5
    assert report['metrics']['labeled_recall'] == .5
    assert report['unjudged_relationships'] == 1
    assert report['tier_observations']['supported']['sample_size'] == 1
    assert report['tier_observations']['unknown']['incorrect'] == 1
    assert report['language_pairs'][0]['source_language'] == 'future-language'


def test_missing_negative_endpoint_is_not_a_true_negative():
    graph, labels = sample()
    graph.nodes = [node for node in graph.nodes if node.id != 'c']
    graph._reindex()
    labels['relationships'][-1]['target'] = 'c'
    report = evaluate_graph(graph, labels)
    assert report['metrics']['false_negative'] == 1
    assert report['metrics']['unscorable_negative'] == 1
    assert report['metrics']['true_negative'] == 0
    assert report['missing_symbols'] == ['c']


def test_empty_denominators_are_null():
    graph, labels = sample()
    labels['relationships'] = labels['relationships'][-1:]
    report = evaluate_graph(graph, labels)
    assert report['metrics']['labeled_precision'] is None
    assert report['metrics']['labeled_recall'] is None


def test_ambiguous_selectors_do_not_get_fuzzy_credit():
    graph, labels = sample()
    labels['symbols']['a'] = {'name': 'same'}
    with pytest.raises(ValueError, match='ambiguous'):
        evaluate_graph(graph, labels)
    labels['symbols']['a']['language'] = 'future-language'
    assert not evaluate_graph(graph, labels)['missing_symbols']


@pytest.mark.parametrize('mutation', ['duplicate', 'contradictory', 'typo', 'nonboolean'])
def test_bad_annotations_fail_loudly(mutation):
    graph, labels = sample()
    if mutation in ('duplicate', 'contradictory'):
        row = copy.deepcopy(labels['relationships'][0])
        if mutation == 'contradictory':
            row['present'] = False
        labels['relationships'].append(row)
    elif mutation == 'typo':
        labels['relationships'][0]['kind'] = 'callls'
    else:
        labels['relationships'][0]['present'] = 'false'
    with pytest.raises(ValueError):
        evaluate_graph(graph, labels)


def test_duplicate_detector_edges_count_as_one_relationship():
    graph, labels = sample()
    graph.add_edge(SemanticEdge('ab2', 'a', 'b', EdgeKind.CALLS, 1))
    assert evaluate_graph(graph, labels)['metrics']['true_positive'] == 1


def test_evaluation_does_not_mutate_graph_and_is_order_independent():
    graph, labels = sample()
    before = copy.deepcopy(graph)
    result = evaluate_graph(graph, labels)
    assert graph == before
    graph.nodes.reverse()
    graph.edges.reverse()
    labels['relationships'].reverse()
    assert evaluate_graph(graph, labels) == result


def test_hand_labeled_multilanguage_adapter_benchmark():
    graph = FeynMapEngine().analyze(str(FIXTURE))
    labels = json.loads((FIXTURE / 'annotations.json').read_text())
    report = evaluate_graph(graph, labels)
    assert report['status'] == 'pass', report
    assert report['metrics']['true_positive'] == 6
    assert report['metrics']['true_negative'] == 2
    assert report['unjudged_relationships'] > 0
    assert any(pair['source_language'] != pair['target_language'] for pair in report['language_pairs'])
    # A plausible hallucinated cross-language edge must fail the benchmark.
    source = next(n for n in graph.nodes if n.name == 'helper' and n.language == 'python')
    target = next(n for n in graph.nodes if n.name == 'helper' and n.language == 'javascript')
    graph.add_edge(SemanticEdge('invented', source.id, target.id, EdgeKind.CALLS, 1))
    assert evaluate_graph(graph, labels)['metrics']['false_positive'] == 1


def test_cli_returns_failure_for_missed_relationship(tmp_path, capsys):
    graph, labels = sample()
    graph_path, labels_path = tmp_path / 'graph.json', tmp_path / 'labels.json'
    graph_path.write_text(json.dumps(graph.to_dict()))
    labels_path.write_text(json.dumps(labels))
    assert main(['evaluate', str(graph_path), str(labels_path)]) == 1
    assert json.loads(capsys.readouterr().out)['metrics']['false_negative'] == 1


def test_dangling_graph_is_rejected_instead_of_scored():
    graph, labels = sample()
    graph.add_edge(SemanticEdge('broken', 'a', 'absent', EdgeKind.CALLS, 1))
    with pytest.raises(ValueError, match='dangling'):
        evaluate_graph(graph, labels)


def test_aliases_cannot_double_count_the_same_judgment():
    graph, labels = sample()
    labels['symbols']['alias_a'] = {'id': 'a'}
    labels['relationships'].append({'source': 'alias_a', 'target': 'b', 'kind': 'calls', 'present': True})
    with pytest.raises(ValueError, match='duplicate'):
        evaluate_graph(graph, labels)
