from __future__ import annotations

import hashlib

import pytest

from hevi.distribution.models import DistributionJob, DistributionPlatform, DistributionTarget
from hevi.distribution.safety import DistributionSafetyError, verify_publishable_source
from hevi.distribution.store import DistributionJobStore


def test_distribution_job_roundtrip_and_atomic_store(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"owned test artifact")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target = DistributionTarget(platform=DistributionPlatform.DOUYIN, account_ref="acct-1", title="test")
    job = DistributionJob(
        distribution_job_id="job-1",
        source_artifact_id="artifact-1",
        source_artifact_sha256=digest,
        provider="matrixmedia",
        platform=target.platform,
        account_ref=target.account_ref,
        title=target.title,
        idempotency_key="same-key",
    )
    store = DistributionJobStore(tmp_path / "jobs.json")
    assert store.put(job).distribution_job_id == "job-1"
    assert store.get("job-1") == job


def test_publish_requires_quality_gate_and_integrity(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"owned test artifact")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(DistributionSafetyError, match="QUALITY_GATE_FAILED"):
        verify_publishable_source(source, expected_sha256=digest, quality_passed=False)
    assert verify_publishable_source(source, expected_sha256=digest, quality_passed=True) == digest


def test_job_states_include_needs_attention() -> None:
    assert DistributionJob.model_fields["state"].annotation is not None
