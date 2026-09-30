"""Regression evidence for reservation and cancellation behavior."""
from fulfillment.models import InventoryItem
from fulfillment.policy import InsufficientStock
from fulfillment.service import cancel_order, reserve_order


def test_insufficient_stock_leaves_quantity_unchanged():
    item = InventoryItem("A-1", 2)
    try:
        reserve_order(item, 3)
    except InsufficientStock:
        assert item.quantity == 2
    else:
        raise AssertionError("Expected InsufficientStock")


def test_successful_reservation_returns_remaining_quantity():
    item = InventoryItem("B-1", 5)
    assert reserve_order(item, 2) == "B-1 reserved=2 remaining=3"


def test_cancel_order_is_policy_only():
    assert cancel_order("queued") is True
    assert cancel_order("shipped") is False
