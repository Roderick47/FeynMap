import unittest

from trace_paths import enumerate_interaction_paths, generate_branch_preserving_ledger


class FakeCache:
    def __init__(self, nodes, edges):
        self.nodes = {node["id"]: node for node in nodes}
        self.edges = edges

    def get_node(self, node_id):
        return self.nodes.get(node_id)

    def get_edges(self, source_node):
        return [edge for edge in self.edges if edge["source"] == source_node]


class BranchPreservingTraceTests(unittest.TestCase):
    def test_branching_graph_produces_independent_paths(self):
        nodes = [
            {"id": "view", "type": "VERTEX", "metadata": {}},
            {"id": "serializer", "type": "TRANSFORM", "metadata": {}},
            {"id": "service", "type": "MEDIATOR", "metadata": {}},
            {"id": "model", "type": "PARTICLE", "metadata": {}},
        ]
        edges = [
            {"source": "view", "target": "serializer", "type": "SERIALIZER_ENTANGLEMENT"},
            {"source": "view", "target": "service", "type": "CALL"},
            {"source": "service", "target": "model", "type": "PARTICLE_ENTANGLEMENT"},
        ]
        cache = FakeCache(nodes, edges)

        paths = enumerate_interaction_paths("view", cache, 4)

        self.assertEqual(2, len(paths))
        self.assertIn(["view", "serializer"], [path["node_ids"] for path in paths])
        self.assertIn(["view", "service", "model"], [path["node_ids"] for path in paths])
        self.assertNotIn(
            ["view", "serializer", "service", "model"],
            [path["node_ids"] for path in paths],
        )

    def test_enhanced_output_contains_paths_and_canonical_graph(self):
        nodes = [
            {"id": "view", "type": "VERTEX", "metadata": {}},
            {"id": "left", "type": "MEDIATOR", "metadata": {}},
            {"id": "right", "type": "MEDIATOR", "metadata": {}},
            {"id": "model", "type": "PARTICLE", "metadata": {}},
        ]
        edges = [
            {"source": "view", "target": "left", "type": "CALL"},
            {"source": "view", "target": "right", "type": "CALL"},
            {"source": "left", "target": "model", "type": "PARTICLE_ENTANGLEMENT"},
            {"source": "right", "target": "model", "type": "PARTICLE_ENTANGLEMENT"},
        ]
        cache = FakeCache(nodes, edges)

        legacy, enhanced = generate_branch_preserving_ledger(
            nodes[0], cache, "backend", 4
        )

        self.assertEqual(2, enhanced["metadata"]["path_count"])
        self.assertTrue(enhanced["metadata"]["branching"])
        self.assertEqual(4, len(enhanced["graph"]["nodes"]))
        self.assertEqual(4, len(enhanced["graph"]["edges"]))
        self.assertIn("PATH 1:", legacy)
        self.assertIn("PATH 2:", legacy)
        self.assertEqual(
            {("view", "left", "model"), ("view", "right", "model")},
            {tuple(path["node_ids"]) for path in enhanced["paths"]},
        )

    def test_cycle_is_reported_without_infinite_recursion(self):
        nodes = [
            {"id": "view", "type": "VERTEX", "metadata": {}},
            {"id": "worker", "type": "MEDIATOR", "metadata": {}},
        ]
        edges = [
            {"source": "view", "target": "worker", "type": "CALL"},
            {"source": "worker", "target": "view", "type": "CALL"},
        ]
        cache = FakeCache(nodes, edges)

        paths = enumerate_interaction_paths("view", cache, 10)

        self.assertEqual(1, len(paths))
        self.assertEqual("cycle", paths[0]["termination"])
        self.assertEqual("view", paths[0]["cycle_to"])
        self.assertEqual(["view", "worker"], paths[0]["node_ids"])

    def test_depth_limit_marks_only_that_path_as_truncated(self):
        nodes = [
            {"id": "view", "type": "VERTEX", "metadata": {}},
            {"id": "a", "type": "MEDIATOR", "metadata": {}},
            {"id": "b", "type": "MEDIATOR", "metadata": {}},
        ]
        edges = [
            {"source": "view", "target": "a", "type": "CALL"},
            {"source": "a", "target": "b", "type": "CALL"},
        ]
        cache = FakeCache(nodes, edges)

        paths = enumerate_interaction_paths("view", cache, 1)

        self.assertEqual(1, len(paths))
        self.assertEqual("max_depth", paths[0]["termination"])
        self.assertEqual(["view", "a"], paths[0]["node_ids"])


if __name__ == "__main__":
    unittest.main()
