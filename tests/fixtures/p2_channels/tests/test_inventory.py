"""Regression tests are supporting evidence, not stock implementation."""
from stockroom.inventory import apply_stock_movement, needs_restock
from stockroom.models import StockRecord


def test_negative_stock_is_rejected():
    item = StockRecord("sku1", quantity=2)
    try:
        apply_stock_movement(item, -3)
    except ValueError:
        assert item.quantity == 2
    else:
        raise AssertionError("Expected a negative-stock rejection")


def test_reorder_point_is_respected():
    assert needs_restock(StockRecord("sku2", quantity=2), reorder_point=3)


def test_unrelated_price_rounding():
    assert round(4.125, 2) == 4.12
