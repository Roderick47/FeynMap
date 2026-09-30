from billing.models import grace_days_default


def apply_grace_days_default(row):
    if "grace_days" not in row:
        row["grace_days"] = grace_days_default()
    return row
