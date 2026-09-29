"""Minimal dispatch state and priority default."""
class Ticket:
    def __init__(self, owner=None, priority=None, escalated=False, closed=False):
        self.owner = owner
        self.priority = priority
        self.escalated = escalated
        self.closed = closed


def default_ticket_priority():
    """Legacy dispatch tickets receive 'normal' priority."""
    return "normal"
