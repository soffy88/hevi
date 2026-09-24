"""Local/file delivery: containment, integrity, idempotency, secret scan."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from hevi.distribution.adapters.local_file import (
    LocalFileDeliveryError,
    LocalFileDeliveryProvider,
    scan_for_secrets,
)
from hevi.distribution.models import DistributionJob, DistributionPlatform
from hevi.distribution.service import create_job, execute_job, job_store, provider_for


def _job(tmp_path: Path, *, key: str = "idem-1", account_ref: str = "acct") -> DistributionJob:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"hevi-owned-delivery-bytes" * 64)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return DistributionJob(
        distribution_job_id="job-1",
        source_artifact_id="artifact-1",
        source_artifact_sha256=digest,
        provider="local_file",
        platform=DistributionPlatform.BILIBILI,
        account_ref=account_ref,
        title="t",
        idempotency_key=key,
    )


def test_destination_stays_inside_delivery_root(tmp_path: Path) -> None:
    provider = LocalFileDeliveryProvider(root=tmp_path / "drop")
    job = _job(tmp_path)
    destination = provider.destination_for(job, tmp_path / "source.mp4")
    assert (tmp_path / "drop").resolve() in destination.parents


@pytest.mark.parametrize("hostile", ["../../escape", "/etc/passwd", "..", "a/b", "~/x"])
def test_adversarial_traversal_is_rejected(tmp_path: Path, hostile: str) -> None:
    provider = LocalFileDeliveryProvider(root=tmp_path / "drop")
    job = _job(tmp_path, account_ref=hostile)
    with pytest.raises(LocalFileDeliveryError, match="UNSAFE_DELIVERY_PATH"):
        provider.destination_for(job, tmp_path / "source.mp4")


def test_hostile_idempotency_key_is_rejected(tmp_path: Path) -> None:
    provider = LocalFileDeliveryProvider(root=tmp_path / "drop")
    job = _job(tmp_path, key="../escape")
    with pytest.raises(LocalFileDeliveryError, match="UNSAFE_DELIVERY_PATH"):
        provider.destination_for(job, tmp_path / "source.mp4")


def test_publish_copies_and_hashes_match(tmp_path: Path) -> None:
    provider = LocalFileDeliveryProvider(root=tmp_path / "drop")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"payload" * 128)
    job = _job(tmp_path)
    result = asyncio.run(provider.publish(job, source))
    assert result.success and result.provider_status == "delivered"
    delivered = Path(result.artifact.uri.replace("file://", ""))
    assert delivered.is_file()
    assert result.artifact.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.duplicate_side_effects == 0


def test_repeat_publish_is_idempotent_no_duplicate_copy(tmp_path: Path) -> None:
    provider = LocalFileDeliveryProvider(root=tmp_path / "drop")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"payload" * 128)
    job = _job(tmp_path)
    first = asyncio.run(provider.publish(job, source))
    before = sorted(item.name for item in (tmp_path / "drop").rglob("*") if item.is_file())
    second = asyncio.run(provider.publish(job, source))
    after = sorted(item.name for item in (tmp_path / "drop").rglob("*") if item.is_file())
    assert first.artifact.sha256 == second.artifact.sha256
    assert before == after
    assert second.provider_status == "idempotent_replay"
    assert second.duplicate_side_effects == 0


def test_source_mutation_after_job_creation_fails_closed(tmp_path: Path) -> None:
    provider = LocalFileDeliveryProvider(root=tmp_path / "drop")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"payload" * 128)
    job = _job(tmp_path)
    source.write_bytes(b"mutated" * 128)
    with pytest.raises(LocalFileDeliveryError, match="PROVENANCE_INCOMPLETE"):
        asyncio.run(provider.publish(job, source))


def test_secret_scan_flags_credential_shaped_values() -> None:
    assert scan_for_secrets({"note": "api_key = abcdef1234567890"})
    assert scan_for_secrets({"note": "sk-abcdefghijklmnopqrst"})
    assert scan_for_secrets({"note": "plain delivery metadata"}) == []


def test_provider_resolution_is_explicit() -> None:
    assert isinstance(provider_for("local_file"), LocalFileDeliveryProvider)
    with pytest.raises(ValueError, match="unknown distribution provider"):
        provider_for("not-a-provider")


def test_service_end_to_end_idempotency_via_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.distribution.models import DistributionTarget

    monkeypatch.setenv("HEVI_DISTRIBUTION_JOB_STORE", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("HEVI_LOCAL_DELIVERY_ROOT", str(tmp_path / "drop"))
    source = tmp_path / "final.mp4"
    source.write_bytes(b"approved-final" * 256)
    target = DistributionTarget(
        platform=DistributionPlatform.BILIBILI, account_ref="local", title="qualification"
    )
    job = create_job(
        source, target, artifact_id="art-1", quality_passed=True, idempotency_key="k-1"
    )
    assert job.provider == "matrixmedia"
    local_job = create_job(
        source,
        target,
        artifact_id="art-1",
        quality_passed=True,
        idempotency_key="k-1",
        provider="local_file",
    )
    first = asyncio.run(execute_job(local_job, source))
    second = asyncio.run(execute_job(local_job, source))
    assert first.success and second.success
    assert first.artifact.sha256 == second.artifact.sha256
    assert second.provider_status == "idempotent_replay"
    store = job_store()
    assert store.get(local_job.distribution_job_id) is not None
    assert store.find_by_idempotency_key("k-1") is not None
    files = [item for item in (tmp_path / "drop").rglob("*") if item.is_file()]
    assert len(files) == 1
