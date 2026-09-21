def merge_headers(defaults, caller_headers):
    """Return request headers assembled from defaults and caller values."""
    merged = dict(caller_headers)
    merged.update(defaults)
    return merged
