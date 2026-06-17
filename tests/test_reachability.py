import unittest

from reachability import analyze_reachability, possibly_unreachable_nodes


class ReachabilityTests(unittest.TestCase):
    def test_traverses_from_http_entry_point(self):
        graph = {
            "nodes": [
                {"id": "view", "name": "View", "type": "VERTEX", "file": "views.py"},
                {"id": "service", "name": "service", "type": "MEDIATOR", "file": "services.py"},
                {"id": "model", "name": "Model", "type": "PARTICLE", "file": "models.py"},
            ],
            "edges": [
                {"source": "view", "target": "service", "type": "CALL"},
                {"source": "service", "target": "model", "type": "PARTICLE_ENTANGLEMENT"},
            ],
        }

        report = analyze_reachability(graph)
        classifications = {item["id"]: item for item in report["nodes"]}

        self.assertEqual("http_entry_point", classifications["view"]["classification"])
        self.assertEqual("reachable", classifications["service"]["classification"])
        self.assertEqual("reachable", classifications["model"]["classification"])

    def test_test_code_is_not_called_dead(self):
        graph = {
            "nodes": [
                {
                    "id": "python:tests.test_orders.test_checkout",
                    "name": "test_checkout",
                    "type": "MEDIATOR",
                    "file": "tests/test_orders.py",
                }
            ],
            "edges": [],
        }

        report = analyze_reachability(graph)
        node = report["nodes"][0]

        self.assertEqual("test_only", node["classification"])
        self.assertNotIn(node["id"], possibly_unreachable_nodes(report))

    def test_framework_loaded_signal_is_protected(self):
        graph = {
            "nodes": [
                {
                    "id": "python:accounts.signals.create_profile",
                    "name": "create_profile",
                    "type": "MEDIATOR",
                    "file": "accounts/signals.py",
                }
            ],
            "edges": [],
        }

        report = analyze_reachability(graph)

        self.assertEqual("framework_entry_point", report["nodes"][0]["classification"])

    def test_dynamic_callback_is_not_called_dead(self):
        graph = {
            "nodes": [
                {
                    "id": "python:plugins.payment_handler",
                    "name": "payment_handler",
                    "type": "MEDIATOR",
                    "file": "plugins.py",
                }
            ],
            "edges": [],
        }

        report = analyze_reachability(graph)

        self.assertEqual("dynamic_reference_suspected", report["nodes"][0]["classification"])

    def test_isolated_plain_utility_is_only_possibly_unreachable(self):
        graph = {
            "nodes": [
                {
                    "id": "python:legacy.normalize_old_value",
                    "name": "normalize_old_value",
                    "type": "MEDIATOR",
                    "file": "legacy.py",
                }
            ],
            "edges": [],
        }

        report = analyze_reachability(graph)
        node = report["nodes"][0]

        self.assertEqual("possibly_unreachable", node["classification"])
        self.assertGreaterEqual(node["confidence"], 0.8)
        self.assertIn(node["id"], possibly_unreachable_nodes(report))

    def test_unreached_node_with_graph_evidence_remains_unknown(self):
        graph = {
            "nodes": [
                {"id": "a", "name": "a", "type": "MEDIATOR", "file": "a.py"},
                {"id": "b", "name": "b", "type": "MEDIATOR", "file": "b.py"},
            ],
            "edges": [{"source": "a", "target": "b", "type": "CALL"}],
        }

        report = analyze_reachability(graph)
        classifications = {item["id"]: item["classification"] for item in report["nodes"]}

        self.assertEqual("isolated_root", classifications["a"])
        self.assertEqual("unknown", classifications["b"])
        self.assertEqual(set(), possibly_unreachable_nodes(report))


if __name__ == "__main__":
    unittest.main()
