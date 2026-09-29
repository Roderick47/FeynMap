"""Irrelevant migration distractor, not opening stock."""


def install_legacy_price_column(rows):
    for row in rows:
        row.setdefault("old_unit_price", None)
    return rows
