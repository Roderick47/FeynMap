import tempfile
import unittest
from pathlib import Path

from feyn_parser import FeynExtractor


class ComponentMetricTests(unittest.TestCase):
    def test_functions_in_same_file_receive_different_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services.py").write_text(
                "def simple(value):\n"
                "    return value\n\n"
                "def complex(value):\n"
                "    total = 0\n"
                "    for item in value:\n"
                "        if item > 0:\n"
                "            total += normalize(item)\n"
                "        else:\n"
                "            total -= 1\n"
                "    return total\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            nodes = {node["name"]: node for node in graph["nodes"]}
            simple = nodes["simple"]["metadata"]
            complex_meta = nodes["complex"]["metadata"]

            self.assertEqual("component", simple["metric_scope"])
            self.assertEqual("component", complex_meta["metric_scope"])
            self.assertLess(simple["metrics"]["loc"], complex_meta["metrics"]["loc"])
            self.assertLess(
                simple["metrics"]["cyclomatic_complexity"],
                complex_meta["metrics"]["cyclomatic_complexity"],
            )
            self.assertLess(simple["mass"], complex_meta["mass"])

    def test_method_metrics_exclude_other_methods_in_same_class(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workers.py").write_text(
                "class Worker:\n"
                "    def tiny(self):\n"
                "        return 1\n\n"
                "    def heavy(self, items):\n"
                "        result = []\n"
                "        for item in items:\n"
                "            if item:\n"
                "                result.append(item)\n"
                "        return result\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            nodes = {node["id"]: node for node in graph["nodes"]}
            tiny = nodes["python:workers.Worker.tiny"]["metadata"]
            heavy = nodes["python:workers.Worker.heavy"]["metadata"]

            self.assertEqual(1, tiny["metrics"]["cyclomatic_complexity"])
            self.assertGreater(heavy["metrics"]["cyclomatic_complexity"], 1)
            self.assertLess(tiny["mass"], heavy["mass"])

    def test_model_fields_are_counted_per_class_not_per_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "models.py").write_text(
                "from django.db import models\n\n"
                "class Small(models.Model):\n"
                "    name = models.CharField(max_length=50)\n\n"
                "class Large(models.Model):\n"
                "    name = models.CharField(max_length=50)\n"
                "    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE)\n"
                "    tags = models.ManyToManyField('Tag')\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="django").scan()
            nodes = {node["name"]: node for node in graph["nodes"]}
            small = nodes["Small"]["metadata"]
            large = nodes["Large"]["metadata"]

            self.assertEqual(1, small["metrics"]["field_count"])
            self.assertEqual(3, large["metrics"]["field_count"])
            self.assertEqual(0, small["metrics"]["relationship_count"])
            self.assertEqual(2, large["metrics"]["relationship_count"])
            self.assertLess(small["mass"], large["mass"])

    def test_nested_function_does_not_inflate_outer_function(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested.py").write_text(
                "def outer(value):\n"
                "    def inner(items):\n"
                "        for item in items:\n"
                "            if item:\n"
                "                print(item)\n"
                "    return value\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            outer = next(node for node in graph["nodes"] if node["name"] == "outer")

            self.assertEqual(1, outer["metadata"]["metrics"]["cyclomatic_complexity"])
            self.assertEqual(0, outer["metadata"]["metrics"]["call_count"])


if __name__ == "__main__":
    unittest.main()
