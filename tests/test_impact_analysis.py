import unittest

from impact_analysis import predict_change_impact


class EvidenceBackedImpactTests(unittest.TestCase):
    def test_strong_edges_produce_high_confidence_candidate(self):
        graph = {
            "nodes": [
                {"id": "model", "type": "PARTICLE", "file": "models.py", "line_start": 1, "line_end": 5},
                {"id": "view", "type": "VERTEX", "file": "views.py", "line_start": 1, "line_end": 5},
            ],
            "edges": [
                {"source": "view", "target": "model", "type": "PARTICLE_ENTANGLEMENT"}
            ],
        }
        diff = """--- a/models.py
+++ b/models.py
@@ -1,1 +1,1 @@
-old
+new
"""

        report = predict_change_impact(graph, diff)
        impacted = report["impacted_nodes"][0]

        self.assertEqual("strong_candidate", impacted["impact_status"])
        self.assertGreaterEqual(impacted["confidence"], 0.8)
        self.assertEqual("high", impacted["confidence_label"])

    def test_low_confidence_edge_is_not_presented_as_certain(self):
        graph = {
            "nodes": [
                {"id": "source", "type": "MEDIATOR", "file": "source.py", "line_start": 1, "line_end": 3},
                {"id": "consumer", "type": "VERTEX", "file": "consumer.py", "line_start": 1, "line_end": 3},
            ],
            "edges": [
                {"source": "consumer", "target": "source", "type": "CALL", "confidence": 0.4}
            ],
        }
        diff = """--- a/source.py
+++ b/source.py
@@ -1,1 +1,1 @@
-old
+new
"""

        report = predict_change_impact(graph, diff)
        impacted = report["impacted_nodes"][0]

        self.assertEqual("possible_candidate", impacted["impact_status"])
        self.assertEqual("low", impacted["confidence_label"])
        self.assertLess(impacted["confidence"], 0.55)

    def test_unmatched_files_reduce_graph_quality(self):
        graph = {"nodes": [], "edges": []}
        diff = """--- a/unmapped.py
+++ b/unmapped.py
@@ -1,1 +1,1 @@
-old
+new
"""

        report = predict_change_impact(graph, diff)

        self.assertIn("unmapped.py", report["graph_quality"]["unmatched_changed_files"])
        self.assertLess(report["graph_quality"]["score"], 1.0)
        self.assertEqual("low", report["risk_summary"]["report_confidence"]["label"])

    def test_unresolved_nodes_are_reported_as_graph_gap(self):
        graph = {
            "nodes": [
                {"id": "model", "type": "PARTICLE", "file": "models.py", "line_start": 1, "line_end": 2},
                {"id": "unresolved:method:save", "type": "MEDIATOR", "file": "views.py"},
            ],
            "edges": [],
        }
        diff = """--- a/models.py
+++ b/models.py
@@ -1,1 +1,1 @@
-old
+new
"""

        report = predict_change_impact(graph, diff)

        self.assertEqual(1, report["graph_quality"]["unresolved_node_count"])
        self.assertTrue(
            any("unresolved symbols" in note for note in report["graph_quality"]["notes"])
        )

    def test_path_records_edge_resolution_evidence(self):
        graph = {
            "nodes": [
                {"id": "helper", "type": "MEDIATOR", "file": "helpers.py", "line_start": 1, "line_end": 2},
                {"id": "view", "type": "VERTEX", "file": "views.py", "line_start": 1, "line_end": 4},
            ],
            "edges": [
                {
                    "source": "view",
                    "target": "helper",
                    "type": "CALL",
                    "confidence": 0.95,
                    "resolution": "qualified_import",
                }
            ],
        }
        diff = """--- a/helpers.py
+++ b/helpers.py
@@ -1,1 +1,1 @@
-old
+new
"""

        report = predict_change_impact(graph, diff)
        path = report["impacted_nodes"][0]["impact_paths"][0]

        self.assertEqual("qualified_import", path["edges"][0]["resolution"])
        self.assertTrue(any("qualified_import" in item for item in path["evidence"]))


if __name__ == "__main__":
    unittest.main()
