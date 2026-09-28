"""Guard against source-archive and editable-install hygiene regressions."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_checkout_is_not_an_implicit_python_package():
    # The real installable library is feynmap/. A root-level __init__.py made
    # pytest treat arbitrary extracted archive directory names as packages.
    assert not (ROOT / "__init__.py").exists()
    assert (ROOT / "feynmap" / "__init__.py").exists()


def test_v2_broken_script_is_not_in_active_checkout():
    assert not (ROOT / "main_broken.py").exists()


def test_rust_build_output_ignore_rules_are_distinct_lines():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/native/routing_kernel/target/" in lines
    assert "/native-dist/" in lines
    assert not any("\\n" in line for line in lines)
