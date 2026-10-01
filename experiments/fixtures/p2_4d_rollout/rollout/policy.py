class RolloutError(Exception):
    pass


class InvalidBatchSize(RolloutError):
    pass


class BatchTooLarge(RolloutError):
    pass


def ensure_rollout_allowed(release, batch_size):
    if batch_size <= 0:
        raise InvalidBatchSize("batch_size must be positive")
    if batch_size > release.remaining_hosts:
        raise BatchTooLarge("batch exceeds remaining hosts")


def can_rollback(status):
    return status in {"rolling", "failed"}
