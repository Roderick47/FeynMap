import pytest

from rollout.models import Release
from rollout.policy import BatchTooLarge
from rollout.service import deploy_batch, request_rollback


def test_oversized_batch_preserves_release_state():
    release = Release("edge-api", 5, "ready")
    with pytest.raises(BatchTooLarge):
        deploy_batch(release, 7)
    assert release.remaining_hosts == 5
    assert release.status == "ready"


def test_exact_batch_completes_rollout():
    release = Release("edge-api", 5, "ready")
    reference = deploy_batch(release, 5)
    assert release.remaining_hosts == 0
    assert release.status == "complete"
    assert reference == "ROLLOUT:edge-api:0"


def test_rollback_policy_allows_active_or_failed_only():
    assert request_rollback("rolling") is True
    assert request_rollback("failed") is True
    assert request_rollback("complete") is False
    assert request_rollback("ready") is False
