"""Useful tests cover both capacity rejection and time escalation."""
from dispatch.models import Ticket
from dispatch.service import assign_ticket, escalate_ticket, finalize_ticket


def test_capacity_rejection_preserves_owner():
    ticket = Ticket(owner="alice")
    try:
        assign_ticket(ticket, "bob", current_load=4, limit=4)
    except ValueError:
        assert ticket.owner == "alice"
    else:
        raise AssertionError("Assignment should have been rejected")


def test_overdue_ticket_escalates():
    ticket = Ticket()
    escalate_ticket(ticket, minutes_open=61, threshold=60)
    assert ticket.escalated is True


def test_unresolved_ticket_cannot_close():
    ticket = Ticket()
    try:
        finalize_ticket(ticket, resolved=False)
    except ValueError:
        assert ticket.closed is False
    else:
        raise AssertionError("Unresolved ticket should not be closed")
