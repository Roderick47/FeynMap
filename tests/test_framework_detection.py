import tempfile
import unittest
from pathlib import Path

from config import detect_framework


class FrameworkDetectionTests(unittest.TestCase):
    def test_detects_django(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manage.py").write_text("import django\n", encoding="utf-8")
            result = detect_framework(root)
            self.assertEqual("django", result.framework)


if __name__ == "__main__":
    unittest.main()
