"""Domain records and defaults for the fresh P2.3b fixture."""


class InventoryItem:
    def __init__(self, sku, quantity):
        self.sku = sku
        self.quantity = quantity


def priority_default():
    """New fulfillment requests begin at normal priority."""
    return "normal"
