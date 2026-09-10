from feynmap.context import ContextBudget, StoredSnapshotContext, estimate_tokens
from feynmap.core import EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge, SemanticGraph, SemanticNode
from feynmap.snapshots import capture_repository_snapshot


def make_context(tmp_path, count=20):
    evidence = [Evidence(EvidenceKind.STATIC, 'fixture', confidence=1)]
    nodes = [SemanticNode('root', 'root', NodeKind.FUNCTION, evidence=evidence)]
    edges = []
    for i in range(count):
        key = 'node%02d' % i
        nodes.append(SemanticNode(key, key, NodeKind.FUNCTION, evidence=evidence))
        edges.append(SemanticEdge('edge%02d' % i, 'root', key, EdgeKind.CALLS, 1, evidence))
    graph = SemanticGraph(nodes, edges)
    return StoredSnapshotContext(capture_repository_snapshot(tmp_path, graph), graph)


def assert_connected(bundle):
    ids = {bundle['root']['id']} | {n['id'] for n in bundle['nodes']}
    reached = {bundle['root']['id']}
    for _ in range(len(ids)):
        for edge in bundle['relationships']:
            assert {edge['source'], edge['target']} <= ids
            if edge['source'] in reached or edge['target'] in reached:
                reached.update((edge['source'], edge['target']))
    assert reached == ids
    assert estimate_tokens(bundle) == bundle['budget']['estimated_tokens']
    assert estimate_tokens(bundle) <= bundle['budget']['max_tokens']


def test_fanout_keeps_connected_evidence_under_budget(tmp_path):
    context = make_context(tmp_path)
    for size in (512, 700, 1100, 2000):
        bundle = context.context_bundle('root', budget=ContextBudget(size, 20, 20))
        assert_connected(bundle)
        if size >= 700:
            assert bundle['relationships']
        assert bundle['budget']['omitted_nodes'] == 20 - len(bundle['nodes'])
        assert bundle['budget']['omitted_relationships'] == 20 - len(bundle['relationships'])


def test_large_candidate_does_not_block_small_candidate(tmp_path):
    context = make_context(tmp_path, 2)
    context.graph.node('node00').name = 'expensive' * 2000
    bundle = context.context_bundle('root', budget=ContextBudget(700, 2, 2))
    assert [node['id'] for node in bundle['nodes']] == ['node01']
    assert_connected(bundle)


def test_behavioral_edges_precede_containment_and_respect_limits(tmp_path):
    context = make_context(tmp_path, 2)
    context.graph.edges[0].kind = EdgeKind.CONTAINS
    bundle = context.context_bundle('root', budget=ContextBudget(2000, 1, 1))
    assert [edge['relationship'] for edge in bundle['relationships']] == ['calls']
    assert bundle['nodes'][0]['id'] == 'node01'
    assert_connected(bundle)


def test_selection_is_independent_of_input_order(tmp_path):
    context = make_context(tmp_path, 8)
    first = context.context_bundle('root', budget=ContextBudget(1100))
    context.graph.nodes.reverse()
    context.graph.edges.reverse()
    context.graph._reindex()
    assert first == context.context_bundle('root', budget=ContextBudget(1100))


def test_multihop_cycle_and_zero_depth(tmp_path):
    context = make_context(tmp_path, 3)
    context.graph.edges[1].source = 'node00'
    context.graph.edges[2].source = 'node01'
    context.graph.add_edge(SemanticEdge('cycle', 'node02', 'node00', EdgeKind.CALLS, 1,
                                      context.graph.nodes[0].evidence))
    context.graph._reindex()
    for depth in (0, 1, 2, 3):
        bundle = context.context_bundle('root', depth=depth, budget=ContextBudget(4000))
        assert_connected(bundle)
        if depth == 0:
            assert not bundle['relationships'] and not bundle['nodes']
        if depth == 1:
            assert {n['id'] for n in bundle['nodes']} == {'node00'}


def test_compact_evidence_keeps_the_basis_for_the_reported_tier(tmp_path):
    context = make_context(tmp_path, 1)
    edge = context.graph.edges[0]
    edge.evidence = [Evidence(EvidenceKind.HEURISTIC, 'a', confidence=1),
                     Evidence(EvidenceKind.HEURISTIC, 'b', confidence=1),
                     Evidence(EvidenceKind.RUNTIME, 'trace', confidence=1)]
    bundle = context.context_bundle('root', budget=ContextBudget(2000))
    relationship = bundle['relationships'][0]
    assert relationship['confidence_tier'] == 'verified'
    assert relationship['evidence'][0]['kind'] == 'runtime_trace'
    assert_connected(bundle)
