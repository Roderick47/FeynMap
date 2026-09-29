"""Different migration intentionally irrelevant to priority initialization."""


def insert_old_billing_code(rows):
    for row in rows:
        row.setdefault("old_billing_code", "-")
    return rows
