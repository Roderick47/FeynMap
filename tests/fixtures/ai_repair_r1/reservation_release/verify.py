from inventory import Inventory


inventory = Inventory(10)
inventory.reserve("order-47", 3)
assert inventory.available == 7
assert inventory.release("order-47") == 3
assert inventory.available == 10
assert inventory.release("order-47") == 0
assert inventory.available == 10
