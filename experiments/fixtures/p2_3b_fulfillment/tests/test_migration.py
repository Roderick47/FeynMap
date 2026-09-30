"""Regression evidence for priority migration."""
import importlib


def test_priority_migration_sets_normal_only_when_missing():
    migration = importlib.import_module("fulfillment.migrations.0001_priority")
    rows = migration.apply_priority_default([
        {"id": 1},
        {"id": 2, "priority": "urgent"},
    ])
    assert rows[0]["priority"] == "normal"
    assert rows[1]["priority"] == "urgent"
