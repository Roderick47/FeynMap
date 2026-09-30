"""A test demonstrating migration behavior; import is deliberately dynamic."""
import importlib


def test_missing_priority_is_backfilled():
    migration = importlib.import_module("dispatch.migrations.0004_backfill_priority")
    items = [{"ticket": 7}]
    migration.backfill_missing_priority(items)
    assert items[0]["priority"] == "normal"


def test_existing_priority_survives():
    migration = importlib.import_module("dispatch.migrations.0004_backfill_priority")
    items = [{"priority": "urgent"}]
    migration.backfill_missing_priority(items)
    assert items[0]["priority"] == "urgent"


def test_unrelated_billing_history():
    migration = importlib.import_module("dispatch.migrations.0005_old_billing")
    items = [{}]
    migration.insert_old_billing_code(items)
    assert items[0]["old_billing_code"] == "-"
