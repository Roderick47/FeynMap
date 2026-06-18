import tempfile
import unittest
from pathlib import Path

from feyn_parser import FeynExtractor
from graph_schema import (
    GRAPH_SCHEMA_VERSION,
    GraphSchemaError,
    normalize_graph,
    schema_compatibility,
    validate_graph,
)


class StableGraphSchemaTests(unittest.TestCase):
    def test_normalizes_legacy_graph_into_v1_contract(self):
        legacy = {
            "nodes": [
                {
                    "id": "python:app.view",
                    "name": "view",
                    "qualified_name": "app.view",
                    "type": "VERTEX",
                    "language": "python",
                    "file": "app.py",
                    "line_start": 3,
                    "line_end": 6,
                    "metadata": {"mass": 0.5},
                    "custom_flag": True,
                },
                {
                    "id": "python:app.helper",
                    "name": "helper",
                    "qualified_name": "app.helper",
                    "type": "MEDIATOR",
                    "language": "python",
                    "file": "app.py",
                    "line_start": 8,
                    "line_end": 9,
                    "metadata": {},
                },
            ],
            "edges": [
                {
                    "source": "python:app.view",
                    "target": "python:app.helper",
                    "type": "CALL",
                    "confidence": 0.9,
                    "resolution": "same_file",
                }
            ],
        }

        graph = normalize_graph(legacy)

        self.assertEqual("feynmap.graph", graph["schema"])
        self.assertEqual(GRAPH_SCHEMA_VERSION, graph["schema_version"])
        self.assertEqual(2, graph["graph"]["node_count"])
        self.assertEqual(1, graph["graph"]["edge_count"])
        self.assertTrue(graph["diagnostics"]["valid"])
        self.assertEqual("app.py", graph["nodes"][0]["source"]["file"])
        self.assertEqual(3, graph["nodes"][0]["source"]["line_start"])
        self.assertTrue(graph["nodes"][0]["attributes"]["custom_flag"])
        self.assertTrue(graph["edges"][0]["id"].startswith("edge:"))
        self.assertEqual("same_file", graph["edges"][0]["resolution"])

    def test_normalization_is_idempotent(self):
        graph = {
            "nodes": [
                {
                    "id": "node:a",
                    "name": "a",
                    "type": "MEDIATOR",
                    "file": "a.py",
                }
            ],
            "edges": [],
        }

        once = normalize_graph(graph)
        twice = normalize_graph(once)

        self.assertEqual(once, twice)

    def test_edge_ids_are_deterministic(self):
        graph = {
            "nodes": [
                {"id": "a", "name": "a", "type": "MEDIATOR"},
                {"id": "b", "name": "b", "type": "MEDIATOR"},
            ],
            "edges": [{"source": "a", "target": "b", "type": "CALL"}],
        }

        first = normalize_graph(graph)["edges"][0]["id"]
        second = normalize_graph(graph)["edges"][0]["id"]

        self.assertEqual(first, second)

    def test_validation_reports_duplicate_node_ids(self):
        graph = normalize_graph(
            {
                "nodes": [
                    {"id": "same", "name": "one", "type": "MEDIATOR"},
                    {"id": "same", "name": "two", "type": "MEDIATOR"},
                ],
                "edges": [],
            }
        )

        diagnostics = validate_graph(graph)

        self.assertFalse(diagnostics["valid"])
        self.assertTrue(any("duplicate node id" in item for item in diagnostics["errors"]))
        with self.assertRaises(GraphSchemaError):
            validate_graph(graph, strict=True)

    def test_rejects_unsupported_future_major_version(self):
        with self.assertRaises(GraphSchemaError):
            normalize_graph(
                {
                    "schema_version": "2.0.0",
                    "nodes": [],
                    "edges": [],
                }
            )

    def test_compatibility_reports_unversioned_migration(self):
        compatibility = schema_compatibility("0.0.0")

        self.assertTrue(compatibility["compatible"])
        self.assertTrue(compatibility["requires_migration"])

    def test_extractor_scan_returns_versioned_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "def helper():\n"
                "    return 1\n\n"
                "def view():\n"
                "    return helper()\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()

            self.assertEqual(GRAPH_SCHEMA_VERSION, graph["schema_version"])
            self.assertEqual(len(graph["nodes"]), graph["graph"]["node_count"])
            self.assertEqual(len(graph["edges"]), graph["graph"]["edge_count"])
            self.assertIn("diagnostics", graph)
            self.assertTrue(all("source" in node for node in graph["nodes"]))
            self.assertTrue(all("id" in edge for edge in graph["edges"]))


if __name__ == "__main__":
    unittest.main()
