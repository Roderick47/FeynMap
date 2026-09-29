"""Seed priority for older ticket rows using the model's explicit default."""
from dispatch.models import default_ticket_priority


def backfill_missing_priority(rows):
    """Existing priorities must remain unchanged."""
    for row in rows:
        if row.get("priority") is None:
            row["priority"] = default_ticket_priority()
    return rows


def reverse_priority_backfill(rows):
    """No destructive reversal of data backfill."""
    return rows
