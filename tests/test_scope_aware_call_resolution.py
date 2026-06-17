import tempfile
import unittest
from pathlib import Path

from feyn_parser import FeynExtractor


class ScopeAwareCallResolutionTests(unittest.TestCase):
    def _call_edges(self, graph):
        return {
            (edge["source"], edge["target"]): edge
            for edge in graph["edges"]
            if edge["type"] == "CALL"
        }

    def test_self_method_resolves_within_its_class(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services.py").write_text(
                "class AccountService:\n"
                "    def save(self):\n"
                "        return 1\n\n"
                "    def run(self):\n"
                "        return self.save()\n\n"
                "class OrderService:\n"
                "    def save(self):\n"
                "        return 2\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            calls = self._call_edges(graph)

            expected = (
                "python:services.AccountService.run",
                "python:services.AccountService.save",
            )
            self.assertIn(expected, calls)
            self.assertEqual("self_method", calls[expected]["resolution"])
            self.assertNotIn(
                (
                    "python:services.AccountService.run",
                    "python:services.OrderService.save",
                ),
                calls,
            )

    def test_calls_inside_methods_are_not_attributed_to_the_class(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services.py").write_text(
                "def helper():\n"
                "    return 1\n\n"
                "class Worker:\n"
                "    def run(self):\n"
                "        return helper()\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            calls = self._call_edges(graph)

            self.assertIn(
                ("python:services.Worker.run", "python:services.helper"), calls
            )
            self.assertNotIn(
                ("python:services.Worker", "python:services.helper"), calls
            )

    def test_direct_import_alias_resolves_exact_function(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "billing"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "calculations.py").write_text(
                "def total():\n    return 100\n", encoding="utf-8"
            )
            (root / "app.py").write_text(
                "from billing.calculations import total as invoice_total\n\n"
                "def checkout():\n"
                "    return invoice_total()\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            calls = self._call_edges(graph)
            edge = calls[("python:app.checkout", "python:billing.calculations.total")]

            self.assertEqual("name", edge["resolution"])

    def test_module_alias_resolves_qualified_function(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "billing"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "calculations.py").write_text(
                "def total():\n    return 100\n", encoding="utf-8"
            )
            (root / "app.py").write_text(
                "import billing.calculations as calc\n\n"
                "def checkout():\n"
                "    return calc.total()\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            calls = self._call_edges(graph)
            edge = calls[("python:app.checkout", "python:billing.calculations.total")]

            self.assertEqual("qualified_import", edge["resolution"])

    def test_local_instance_method_resolves_from_constructor_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services.py").write_text(
                "class AccountService:\n"
                "    def save(self):\n"
                "        return 1\n\n"
                "def execute():\n"
                "    service = AccountService()\n"
                "    return service.save()\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            calls = self._call_edges(graph)
            edge = calls[("python:services.execute", "python:services.AccountService.save")]

            self.assertEqual("local_instance", edge["resolution"])

    def test_ambiguous_unqualified_call_does_not_create_false_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "accounts.py").write_text(
                "def save():\n    return 1\n", encoding="utf-8"
            )
            (root / "orders.py").write_text(
                "def save():\n    return 2\n", encoding="utf-8"
            )
            (root / "app.py").write_text(
                "def execute():\n    return save()\n", encoding="utf-8"
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            calls = self._call_edges(graph)

            self.assertFalse(
                any(source == "python:app.execute" for source, _ in calls)
            )


if __name__ == "__main__":
    unittest.main()
