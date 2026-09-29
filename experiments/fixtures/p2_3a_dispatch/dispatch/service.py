"""Source task-bearing entrypoints; all dependencies are explicit imports."""
from dispatch.models import Ticket
from dispatch.policy import check_capacity, may_close, needs_escalation


def assign_ticket(ticket: Ticket, employee, current_load, limit):
    """Validate capacity before mutating ticket owner."""
    check_capacity(current_load, limit)
    ticket.owner = employee
    return ticket


def escalate_ticket(ticket: Ticket, minutes_open, threshold):
    """Use the independent threshold rule before escalating."""
    if needs_escalation(minutes_open, threshold):
        ticket.escalated = True
    return ticket


def finalize_ticket(ticket: Ticket, resolved):
    """Closing is guarded by a separate source-backed policy."""
    may_close(resolved)
    ticket.closed = True
    return ticket
