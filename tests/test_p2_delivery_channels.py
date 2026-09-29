"""P2.1: source-role preferences must not mutate graph truth or P1 defaults."""
import pytest

from feynmap.context import estimate_tokens
from feynmap.core import (
    EdgeKind, Evidence, EvidenceKind, NodeKind, SemanticEdge,
    SemanticGraph, SemanticNode, SourceLocation,
)
from feynmap.delivery_channels import (
    CONFIGURATION, DOCUMENTATION, IMPLEMENTATION, MIGRATION, TEST, VENDOR,
    DeliveryChannelPolicy, channel_counts, file_channel, task_channel,
)
from feynmap.judgment.search import GuidedSearchResult, SearchHit
from feynmap.minimal_context import MinimalContextBudget, MinimalContextPacker


def _node(identifier, path, name=None):
    return SemanticNode(
        id=identifier,
        name=name or identifier,
        qualified_name=(path.replace("/", ".").replace(".py", "") + "." + (name or identifier)),
        kind=NodeKind.FUNCTION,
        language="python",
        location=SourceLocation(path=path, line=3),
        evidence=[Evidence(
            EvidenceKind.STATIC, "python.ast.definition",
            "Source definition", SourceLocation(path=path, line=3), 1.0,
        )],
    )


def _result(query="How are serializer fields and validation resolved?"):
    root = _node("test-root", "tests/test_serializers.py", "test_serializer_validation")
    serializer = _node("serializer", "src/serializers.py", "_get_declared_fields")
    field = _node("field", "src/fields.py", "Field")
    test_nodes = [
        _node("test-%d" % i, "tests/test_case_%02d.py" % i,
              "test_serializer_fields_validation_%d" % i)
        for i in range(11)
    ]
    migration = _node("migration", "src/migrations/0001_initial.py", "Migration")
    other = _node("other", "src/models.py", "Model")
    vendor = _node("vendor", "vendor/tests/test_minified.py", "bundled_asset")
    nodes = [root, serializer, field] + test_nodes + [migration, other, vendor]
    edges = []
    def link(identifier, src, tgt, kind):
        edge = SemanticEdge(
            identifier, src.id, tgt.id, kind, 0.98,
            [Evidence(
                EvidenceKind.STATIC, "python.ast.call",
                "Explicit source use", SourceLocation("src/serializers.py", line=8),
                0.98,
            )],
        )
        edges.append(edge)
        return edge
    source_link = link("root-calls-impl", root, serializer, EdgeKind.CALLS)
    bridge = link("impl-field", serializer, field, EdgeKind.USES_DATA)
    test_edges = [
        link("root-to-test-%d" % i, root, test_node, EdgeKind.CALLS)
        for i, test_node in enumerate(test_nodes)
    ]
    extra_edges = [
        link("root-to-%s" % item.id, root, item, EdgeKind.IMPORTS)
        for item in (migration, other, vendor)
    ]
    hits = [SearchHit(root, depth=0)]
    hits += [
        SearchHit(test_node, depth=1, parent_id=root.id, via_edge_id=edge.id)
        for test_node, edge in zip(test_nodes, test_edges)
    ]
    hits += [
        SearchHit(serializer, depth=1, parent_id=root.id,
                  via_edge_id=source_link.id),
        SearchHit(field, depth=2, parent_id=serializer.id,
                  via_edge_id=bridge.id),
    ]
    hits += [
        SearchHit(node, depth=1, parent_id=root.id, via_edge_id=edge.id)
        for node, edge in zip((migration, other, vendor), extra_edges)
    ]
    graph = SemanticGraph(nodes=nodes, edges=edges)
    result = GuidedSearchResult(
        mode="concept", query=query, roots=[root], hits=hits,
        edges=edges, trace=[], provider=None, model=None,
        exhausted=True, truncated=False,
    )
    return graph, result


def _paths(graph, packed):
    return {
        graph.node(node_id).location.path
        for node_id in packed.selected_node_ids
        if graph.node(node_id).location
    }


def test_source_channel_labels_are_path_based_and_bounded():
    cases = {
        "rest_framework/serializers.py": IMPLEMENTATION,
        "rest_framework/fields.py": IMPLEMENTATION,
        "tests/test_validation.py": TEST,
        "pkg/tests/test_api.py": TEST,
        "src/parser.test.ts": TEST,
        "catalog/migrations/0001_initial.py": MIGRATION,
        "tests/migrations/0002.py": MIGRATION,
        "vendor/tests/test_dependency.py": VENDOR,
        "rest_framework/static/rest_framework/js/jquery.min.js": VENDOR,
        "generated/client.js": VENDOR,
        "docs/user-guide.md": DOCUMENTATION,
        "pyproject.toml": CONFIGURATION,
        "src/api.py": IMPLEMENTATION,
        "src/notatestclass.py": IMPLEMENTATION,
    }
    for path, expected in cases.items():
        assert file_channel(path) == expected, path
    assert file_channel(None) == IMPLEMENTATION
    assert task_channel("Why does serializer validation work?") == IMPLEMENTATION
    assert task_channel("Which test fixture covers it?") == TEST
    assert task_channel("Explain the schema migration") == MIGRATION
    assert task_channel("Inspect the vendored minified bundle") == VENDOR
    with pytest.raises(ValueError, match="unsupported"):
        DeliveryChannelPolicy(mode="oracle").normalized()
    with pytest.raises(ValueError, match="max_test_fraction"):
        DeliveryChannelPolicy(max_test_fraction=1.5).normalized()


def test_legacy_no_policy_is_bitwise_unchanged():
    graph, result = _result()
    packer = MinimalContextPacker(graph)
    budget = MinimalContextBudget(
        max_tokens=3200, max_nodes=8, max_edges=8,
        initial_tokens=3200,
    )
    direct = packer.pack(result, budget=budget)
    explicitly_none = packer.pack(result, budget=budget, delivery_policy=None)
    assert direct.to_dict() == explicitly_none.to_dict()


def test_source_first_delivers_distinct_activated_implementation_files():
    graph, result = _result()
    budget = MinimalContextBudget(
        max_tokens=3200, max_nodes=8, max_edges=8, initial_tokens=3200,
    )
    packed = MinimalContextPacker(graph).pack(
        result, budget=budget, delivery_policy=DeliveryChannelPolicy(),
    )
    selected = set(packed.selected_node_ids)
    assert {"serializer", "field"}.issubset(selected)
    assert {"src/serializers.py", "src/fields.py"}.issubset(_paths(graph, packed))
    assert packed.sufficient
    assert packed.delivered_nodes <= budget.max_nodes
    assert packed.delivered_tokens <= budget.max_tokens
    assert packed.delivered_tokens == estimate_tokens(packed.payload)
    assert set(packed.selected_edge_ids) <= {edge.id for edge in result.edges}
    for edge_id in packed.selected_edge_ids:
        edge = next(edge for edge in result.edges if edge.id == edge_id)
        assert {edge.source, edge.target} <= selected
    counts = channel_counts(graph.node(node_id) for node_id in selected)
    assert counts.get(TEST, 0) <= 3
    assert counts.get(IMPLEMENTATION, 0) >= 2
    assert counts.get(TEST, 0) >= 1  # first activated root


def test_role_policy_never_delivers_a_file_not_in_activated_search():
    graph, original = _result()
    hits = [hit for hit in original.hits if hit.node.id != "field"]
    edges = [
        edge for edge in original.edges
        if edge.source != "field" and edge.target != "field"
    ]
    result = GuidedSearchResult(
        mode=original.mode, query=original.query, roots=original.roots,
        hits=hits, edges=edges, trace=original.trace, provider=original.provider,
        model=original.model, exhausted=original.exhausted,
        truncated=original.truncated,
    )
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(
            max_tokens=3200, max_nodes=8, max_edges=8, initial_tokens=3200,
        ),
        delivery_policy=DeliveryChannelPolicy(),
    )
    assert "field" not in packed.selected_node_ids
    assert "src/fields.py" not in _paths(graph, packed)


def test_explicit_test_and_migration_queries_keep_task_specific_channels():
    budget = MinimalContextBudget(
        max_tokens=3200, max_nodes=9, max_edges=9, initial_tokens=3200,
    )
    for query, required in (
        ("Which tests cover serializer validation?", TEST),
        ("Explain the schema migrations and changes", MIGRATION),
        ("Inspect the vendored generated bundle", VENDOR),
    ):
        graph, result = _result(query=query)
        packed = MinimalContextPacker(graph).pack(
            result, budget=budget, delivery_policy=DeliveryChannelPolicy(),
        )
        channel_by_node = channel_counts(
            graph.node(node_id) for node_id in packed.selected_node_ids
        )
        assert channel_by_node.get(required, 0) >= 1, (
            query, channel_by_node, packed.critical_node_ids,
        )
        assert packed.delivered_tokens <= budget.max_tokens
        assert all(graph.node(node_id) is not None
                   for node_id in packed.selected_node_ids)



def test_explicit_test_task_retains_tests_when_primary_root_is_implementation():
    graph, original = _result(query="Which tests cover serializer validation?")
    implementation = next(hit.node for hit in original.hits if hit.node.id == "serializer")
    # This test does not rely on a conveniently test-shaped primary root:
    # a source implementation may be the already activated search entrypoint.
    hits = [
        SearchHit(implementation, depth=0),
    ] + [hit for hit in original.hits if hit.node.id != "serializer"]
    result = GuidedSearchResult(
        mode=original.mode, query=original.query, roots=[implementation],
        hits=hits, edges=original.edges, trace=original.trace,
        provider=original.provider, model=original.model,
        exhausted=original.exhausted, truncated=original.truncated,
    )
    packed = MinimalContextPacker(graph).pack(
        result, budget=MinimalContextBudget(
            max_tokens=3200, max_nodes=9, max_edges=9, initial_tokens=3200,
        ), delivery_policy=DeliveryChannelPolicy(),
    )
    counts = channel_counts(
        graph.node(node_id) for node_id in packed.selected_node_ids
    )
    assert counts.get(TEST, 0) >= 1
    assert counts.get(IMPLEMENTATION, 0) >= 1
    assert "serializer" in packed.selected_node_ids
    assert packed.sufficient


def test_public_role_aware_policy_does_not_alter_existing_context_schema():
    from feynmap import DeliveryChannelPolicy as PublicPolicy
    from feynmap import file_channel as public_channel
    assert PublicPolicy is DeliveryChannelPolicy
    assert public_channel("tests/test_api.py") == TEST
    graph, result = _result()
    packed = MinimalContextPacker(graph).pack(
        result,
        budget=MinimalContextBudget(max_tokens=3200, max_nodes=8, max_edges=8,
                                    initial_tokens=3200),
        delivery_policy=PublicPolicy(),
    )
    assert set(packed.payload) == {
        "query", "anchors", "nodes", "relationships", "grounding",
    }
    assert "role_aware" not in packed.payload
