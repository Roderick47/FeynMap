"""A migration-specific test, not a replacement for reading the migration."""
import importlib


def test_opening_stock_migration_sets_zero():
    migration = importlib.import_module("stockroom.migrations.0001_opening_stock")
    result = migration.apply_opening_stock([{"sku": "new"}])
    assert result[0]["quantity"] == 0


def test_legacy_pricing_migration_does_not_initialize_quantity():
    migration = importlib.import_module("stockroom.migrations.0002_legacy_pricing")
    result = migration.install_legacy_price_column([{"sku": "old"}])
    assert "quantity" not in result[0]
