class Inventory:
    def __init__(self, available):
        self.available = available
        self.reservations = {}

    def reserve(self, reservation_id, quantity):
        if quantity > self.available:
            raise ValueError("insufficient inventory")
        self.available -= quantity
        self.reservations[reservation_id] = quantity

    def release(self, reservation_id):
        quantity = self.reservations.get(reservation_id, 0)
        self.available += quantity
        return quantity
