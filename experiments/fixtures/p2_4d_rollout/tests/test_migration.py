import importlib


def test_health_window_default_only_fills_missing_value():
    migration = importlib.import_module("rollout.migrations.0001_health_window")
    rows = [
        {"name": "edge-api"},
        {"name": "worker", "health_window_minutes": 30},
    ]
    result = migration.apply_health_window_default(rows)
    assert result[0]["health_window_minutes"] == 15
    assert result[1]["health_window_minutes"] == 30
