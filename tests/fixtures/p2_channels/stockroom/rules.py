"""Implementation rules; neither tests nor migrations are authoritative here."""


def validate_adjustment(current_quantity, delta):
    """Reject an adjustment that would make physical stock negative."""
    if current_quantity + delta < 0:
        raise ValueError("Stock cannot be negative")
    return True


def is_reorder_required(current_quantity, reorder_point):
    """True when an SKU falls below its configured reorder point."""
    return current_quantity < reorder_point


def unrelated_discount_rule(unit_price):
    """Distractor: product price has no part in physical stock movement."""
    return round(unit_price * 0.95, 2)
