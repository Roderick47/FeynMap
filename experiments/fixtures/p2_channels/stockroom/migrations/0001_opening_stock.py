"""Source-authored opening-stock migration; separate from the implementation."""
from stockroom.models import stock_default_value


class Migration:
    """Seed missing quantity values to the implementation-defined zero default."""

    def forwards(self, rows):
        for row in rows:
            if "quantity" not in row:
                row["quantity"] = stock_default_value()
        return rows

    def backwards(self, rows):
        return rows


def apply_opening_stock(rows):
    """Public migration entrypoint, not a production inventory operation."""
    return Migration().forwards(rows)
