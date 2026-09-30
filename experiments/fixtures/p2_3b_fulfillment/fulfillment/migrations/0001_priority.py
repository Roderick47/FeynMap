"""Initialize missing request priority from the domain default."""
from fulfillment.models import priority_default


def apply_priority_default(rows):
    for row in rows:
        if "priority" not in row:
            row["priority"] = priority_default()
    return rows
