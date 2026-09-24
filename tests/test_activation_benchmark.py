import json

from feynmap.activation_benchmark import BENCHMARK_SCHEMA, run_benchmark


def test_sparse_activation_benchmark_measures_recall_and_sparsity(tmp_path):
    (tmp_path / "app.py").write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )

    dataset = {
        "schema": BENCHMARK_SCHEMA,
        "name": "tiny",
        "analysis": {"language": "python", "framework": "none"},
        "tasks": [
            {
                "id": "find-helper",
                "mode": "node",
                "root": "app.run",
                "query": "Find the helper used by run",
                "essential_files": ["app.py"],
                "essential_symbols": ["app.helper"],
                "search": {
                    "max_depth": 2,
                    "beam_width": 4,
                    "max_nodes": 8,
                    "direction": "both",
                },
            }
        ],
    }

    result = run_benchmark(str(tmp_path), dataset)
    assert result["schema"] == BENCHMARK_SCHEMA
    assert result["analysis"]["graph_nodes"] >= 2
    assert result["analysis"]["elapsed_ms"] >= 0
    assert result["task_count"] == 1

    task = result["tasks"][0]
    assert task["essential_recall"] == 1.0
    assert task["essential_full_recall"] is True
    assert task["metrics"]["activated_nodes"] >= 2
    assert task["metrics"]["routing_elapsed_ms"] >= 0
    assert task["metrics"]["activated_context_tokens"] > 0
    assert 0 <= task["metrics"]["knowledge_activation_ratio"] <= 1
    assert result["summary"]["mean_essential_recall"] == 1.0


def test_dataset_files_are_valid_json():
    for path in (
        "experiments/sparse_activation_feynmap_s0.json",
        "experiments/sparse_activation_wikonomi_s0.json",
    ):
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        assert payload["schema"] == BENCHMARK_SCHEMA
        assert payload["tasks"]



def test_sparse_activation_benchmark_supports_region_strategy(tmp_path):
    (tmp_path / "app.py").write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def run():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "signals.py").write_text(
        "def refresh_stale_price():\n"
        "    return True\n",
        encoding="utf-8",
    )

    dataset = {
        "schema": BENCHMARK_SCHEMA,
        "name": "region-tiny",
        "analysis": {"language": "python", "framework": "none"},
        "tasks": [
            {
                "id": "find-refresh",
                "mode": "node",
                "root": "app.run",
                "query": "refresh stale price",
                "essential_files": ["signals.py"],
                "search": {
                    "max_depth": 1,
                    "beam_width": 4,
                    "max_nodes": 8,
                    "direction": "both",
                },
            }
        ],
    }

    result = run_benchmark(
        str(tmp_path),
        dataset,
        strategy="region",
        region_limit=2,
        region_seed_limit=4,
    )
    assert result["strategy"] == "region"
    assert result["tasks"][0]["region_route"] is not None
    assert result["tasks"][0]["essential_recall"] == 1.0
    assert result["summary"]["mean_region_touch_ratio"] is not None
