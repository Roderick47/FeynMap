import tempfile
import unittest
from pathlib import Path

from feyn_parser import FeynExtractor


class UniqueNodeIdentityTests(unittest.TestCase):
    def test_duplicate_function_names_in_different_modules_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "accounts.py").write_text(
                "def save():\n    return 'accounts'\n", encoding="utf-8"
            )
            (root / "orders.py").write_text(
                "def save():\n    return 'orders'\n", encoding="utf-8"
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            save_nodes = [node for node in graph["nodes"] if node.get("name") == "save"]

            self.assertEqual(2, len(save_nodes))
            self.assertEqual(
                {"python:accounts.save", "python:orders.save"},
                {node["id"] for node in save_nodes},
            )

    def test_duplicate_methods_in_different_classes_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services.py").write_text(
                "class AccountService:\n"
                "    def save(self):\n"
                "        return 1\n\n"
                "class OrderService:\n"
                "    def save(self):\n"
                "        return 2\n",
                encoding="utf-8",
            )

            graph = FeynExtractor(str(root), framework="generic").scan()
            save_nodes = [node for node in graph["nodes"] if node.get("name") == "save"]

            self.assertEqual(
                {
                    "python:services.AccountService.save",
                    "python:services.OrderService.save",
                },
                {node["id"] for node in save_nodes},
            )

    def test_templates_with_same_filename_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "accounts" / "templates" / "detail.html"
            second = root / "orders" / "templates" / "detail.html"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text("{{ account.name }}", encoding="utf-8")
            second.write_text("{{ order.name }}", encoding="utf-8")

            graph = FeynExtractor(str(root), framework="django").scan()
            templates = [node for node in graph["nodes"] if node["type"] == "FRONTEND"]

            self.assertEqual(2, len(templates))
            self.assertEqual(
                {
                    "template:accounts/templates/detail.html",
                    "template:orders/templates/detail.html",
                },
                {node["id"] for node in templates},
            )


if __name__ == "__main__":
    unittest.main()
