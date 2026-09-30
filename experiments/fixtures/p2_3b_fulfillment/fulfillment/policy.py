"""Stock and authorization policies for the fresh P2.3b fixture."""


class InsufficientStock(ValueError):
    pass


def ensure_stock(item, requested_quantity):
    """Reject a reservation that exceeds currently available stock."""
    if requested_quantity > item.quantity:
        raise InsufficientStock("requested quantity exceeds available stock")
    return True


def can_cancel(status):
    """Only queued or packed fulfillment requests may be cancelled."""
    return status in {"queued", "packed"}
