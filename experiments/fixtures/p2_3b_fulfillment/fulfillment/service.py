"""Fulfillment operations for the fresh P2.3b fixture."""
from fulfillment.audit import reservation_message
from fulfillment.policy import can_cancel, ensure_stock


def reserve_order(item, requested_quantity):
    """Validate before mutating stock, then return a grounded audit message."""
    ensure_stock(item, requested_quantity)
    item.quantity -= requested_quantity
    return reservation_message(item.sku, requested_quantity, item.quantity)


def cancel_order(status):
    """Return cancellation eligibility; no refund side effect exists here."""
    return can_cancel(status)
