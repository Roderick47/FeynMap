"""P1.1 source-authored external framework probes remain version-pinned."""
import json
import re
from pathlib import Path


MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "experiments" / "p1_external_framework_manifest.json"
)


def test_p1_external_manifest_is_immutable_revision_based():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "feynmap.external_framework_baseline.v1"
    assert len(data["fixtures"]) == 3
    assert {case["id"] for case in data["fixtures"]} == {
        "mdn-django-local-library",
        "grinberg-microblog",
        "django-rest-framework",
    }
    for case in data["fixtures"]:
        assert re.fullmatch(r"[a-f0-9]{40}", case["commit"]), case["id"]
        assert "/" in case["repository"]
        assert case["probes"]


def test_p1_probes_are_independently_stated_not_generated_results():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases = [p for item in data["fixtures"] for p in item["probes"]]
    assert len(cases) == 11
    assert len({case["id"] for case in cases}) == 11
    for case in cases:
        assert case["basis"].strip()
        assert case["expected_status"] in {
            "supported", "framework_inferred", "required_evidence", "no_crash"
        }
        assert not any(
            name in case for name in ("observed", "passed", "feynmap_result")
        )


def test_pinned_microblog_requires_registered_prefix_not_raw_decorator():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    microblog = next(
        item for item in data["fixtures"] if item["id"] == "grinberg-microblog"
    )
    assert {item["expected_method"] for item in microblog["probes"]} == {
        "POST", "DELETE"
    }
    assert all(
        item["expected_path"] == "/api/tokens"
        for item in microblog["probes"]
    )
