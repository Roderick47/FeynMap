"""Source facts for stockroom opening quantities."""


class StockRecord:
    """One stockkeeping unit and its current physical quantity."""

    def __init__(self, sku, quantity=0):
        self.sku = sku
        self.quantity = quantity


def stock_default_value():
    """Opening-stock migration uses zero units for new records."""
    return 0
