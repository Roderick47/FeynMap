import importlib


grace_migration = importlib.import_module("billing.migrations.0001_grace_days")


def test_grace_days_default_only_fills_missing_value():
    missing = {}
    existing = {"grace_days": 14}
    assert grace_migration.apply_grace_days_default(missing)["grace_days"] == 7
    assert grace_migration.apply_grace_days_default(existing)["grace_days"] == 14
