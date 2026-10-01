from .audit import rollout_reference
from .policy import can_rollback, ensure_rollout_allowed


def deploy_batch(release, batch_size):
    ensure_rollout_allowed(release, batch_size)
    release.remaining_hosts -= batch_size
    if release.remaining_hosts == 0:
        release.status = "complete"
    else:
        release.status = "rolling"
    return rollout_reference(release)


def request_rollback(status):
    return can_rollback(status)
