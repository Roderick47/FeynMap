from .audit import payment_reference
from .policy import can_retry, ensure_payment_allowed


def apply_payment(invoice, payment_cents):
    ensure_payment_allowed(invoice.outstanding_cents, payment_cents)
    invoice.outstanding_cents -= payment_cents
    if invoice.outstanding_cents == 0:
        invoice.status = "paid"
    return payment_reference(invoice.id, invoice.outstanding_cents)


def retry_payment(status):
    return can_retry(status)
