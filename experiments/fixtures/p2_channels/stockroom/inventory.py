"""Production implementation: stock operations call independently defined rules."""
from stockroom.models import StockRecord
from stockroom.rules import is_reorder_required, validate_adjustment


def apply_stock_movement(record: StockRecord, delta: int) -> int:
    """Validate stock quantity before committing a movement."""
    validate_adjustment(record.quantity, delta)
    record.quantity += delta
    return record.quantity


def needs_restock(record: StockRecord, reorder_point: int) -> bool:
    """Delegate reorder decisions to the independent rule."""
    return is_reorder_required(record.quantity, reorder_point)
