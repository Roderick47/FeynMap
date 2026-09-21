def retry_delay(attempt, base_seconds=1):
    """Return the delay before a zero-based retry attempt."""
    if attempt < 0:
        raise ValueError("attempt must be non-negative")
    return base_seconds * (2 ** attempt)
