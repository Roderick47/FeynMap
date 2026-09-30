"""Audit message formatting only; no file or database writes happen here."""


def reservation_message(sku, reserved_quantity, remaining_quantity):
    return "%s reserved=%s remaining=%s" % (
        sku, reserved_quantity, remaining_quantity,
    )
