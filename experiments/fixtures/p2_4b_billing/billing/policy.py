class OverpaymentError(ValueError):
    pass


def ensure_payment_allowed(outstanding_cents, payment_cents):
    if payment_cents <= 0:
        raise ValueError("payment must be positive")
    if payment_cents > outstanding_cents:
        raise OverpaymentError("payment exceeds outstanding balance")


def can_retry(status):
    return status in {"declined", "timeout"}
