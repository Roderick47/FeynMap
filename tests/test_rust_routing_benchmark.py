from pathlib import Path

import pytest

from feynmap.rust_routing_benchmark import BENCHMARK_SCHEMA, run_benchmark, validate_spec


def _spec():
    return {
        "schema": BENCHMARK_SCHEMA,
        "name": "fixture",
        "analysis": {"language": "python", "framework": "none"},
        "warmup_rounds": 1,
        "measurement_rounds": 2,
        "region_limit": 2,
        "tasks": [
            {
                "id": "route-run",
                "root": "app.run",
                "query": "run helper execution",
            }
        ],
    }


def test_rust_routing_benchmark_pins_reference_signature(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )

    result = run_benchmark(str(tmp_path), _spec())

    assert result["implementation"] == "python-reference"
    assert result["workload"]["route_calls"] == 2
    assert result["region_index"]["region_count"] >= 1
    assert result["timing"]["mean_route_us"] >= 0.0
    signature = result["signatures"]["route-run"]
    assert signature["anchor_region"] == "app.py"
    assert signature["selected_regions"][0] == "app.py"


def test_rust_routing_benchmark_rejects_invalid_rounds():
    spec = _spec()
    spec["measurement_rounds"] = 0

    with pytest.raises(ValueError, match="measurement_rounds"):
        validate_spec(spec)
