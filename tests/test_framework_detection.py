import tempfile
import unittest
from pathlib import Path

from config import detect_framework, get_framework_config
from feyn_parser import FeynExtractor


class FrameworkDetectionTests(unittest.TestCase):
    def test_detects_django(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manage.py").write_text("import django\n", encoding="utf-8")
            result = detect_framework(root)
            self.assertEqual("django", result.framework)
            self.assertGreaterEqual(result.confidence, 0.8)

    def test_detects_flask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "from flask import Flask\napp = Flask(__name__)\n",
                encoding="utf-8",
            )
            result = detect_framework(root)
            self.assertEqual("flask", result.framework)

    def test_detects_fastapi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "from fastapi import FastAPI, APIRouter\napp = FastAPI()\nrouter = APIRouter()\n",
                encoding="utf-8",
            )
            result = detect_framework(root)
            self.assertEqual("fastapi", result.framework)

    def test_generic_project_does_not_default_to_django(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "calculator.py").write_text(
                "def add(left, right):\n    return left + right\n",
                encoding="utf-8",
            )
            result = detect_framework(root)
            self.assertEqual("generic", result.framework)
            self.assertEqual(0.0, result.confidence)

    def test_extractor_auto_uses_detected_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manage.py").write_text("import django\n", encoding="utf-8")
            extractor = FeynExtractor(str(root), framework="auto")
            extractor.scan()
            self.assertEqual("django", extractor.config.framework_name)
            self.assertEqual("django", extractor.config.detection_result.framework)

    def test_explicit_framework_bypasses_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = get_framework_config("fastapi", root)
            self.assertEqual("fastapi", config.framework_name)
            self.assertIsNone(config.detection_result)


if __name__ == "__main__":
    unittest.main()
