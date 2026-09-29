"""Independent policy checks for ticket operations."""


def check_capacity(current_load, limit):
    """Assignment is rejected once the employee reaches maximum capacity."""
    if current_load >= limit:
        raise ValueError("Dispatch capacity exceeded")
    return True


def needs_escalation(minutes_open, threshold):
    """Escalate an unresolved dispatch ticket at or beyond threshold."""
    return minutes_open >= threshold


def may_close(resolved):
    """Only resolved tickets may be finalized."""
    if not resolved:
        raise ValueError("Ticket remains unresolved")
    return True


def unrelated_invoice_discount(amount):
    """Explicitly irrelevant pricing distractor."""
    return round(amount * 0.9, 2)
