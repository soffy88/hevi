from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from hevi.distribution.adapters.local_file import local_file_provider
from hevi.distribution.adapters.matrixmedia import MatrixMediaDistributionProvider
from hevi.distribution.models import (
    DistributionJob,
    DistributionJobState,
    DistributionResult,
    DistributionTarget,
)
from hevi.distribution.provider import DistributionProvider
from hevi.distribution.safety import verify_publishable_source
from hevi.distribution.store import DistributionJobStore


def matrixmedia_provider() -> MatrixMediaDistributionProvider:
    return MatrixMediaDistributionProvider(
        timeout_s=float(os.getenv("MATRIXMEDIA_TIMEOUT_S", "60"))
    )


def provider_for(name: str | None = None) -> DistributionProvider:
    """Resolve the configured distribution provider; never substitute silently."""

    requested = (name or os.getenv("HEVI_DISTRIBUTION_PROVIDER") or "matrixmedia").strip().lower()
    if requested in {"local_file", "local-file", "local"}:
        return local_file_provider()
    if requested == "matrixmedia":
        return matrixmedia_provider()
    raise ValueError(f"unknown distribution provider: {requested}")


def job_store() -> DistributionJobStore:
    return DistributionJobStore(
        os.getenv("HEVI_DISTRIBUTION_JOB_STORE", "data/distribution/jobs.json")
    )


def create_job(
    source: str | Path,
    target: DistributionTarget,
    *,
    artifact_id: str,
    quality_passed: bool,
    idempotency_key: str | None = None,
    provider: str | None = None,
) -> DistributionJob:
    source_path = Path(source).expanduser().resolve()
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path.is_file() else ""
    verify_publishable_source(source_path, expected_sha256=digest, quality_passed=quality_passed)
    job = DistributionJob(
        distribution_job_id=str(uuid.uuid4()),
        source_artifact_id=artifact_id,
        source_artifact_sha256=digest,
        provider=(provider or os.getenv("HEVI_DISTRIBUTION_PROVIDER") or "matrixmedia"),
        platform=target.platform,
        account_ref=target.account_ref,
        title=target.title,
        description=target.description,
        tags=target.tags,
        scheduled_at=target.scheduled_at,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        state=DistributionJobState.VALIDATING,
    )
    return job_store().put(job)


async def execute_job(
    job: DistributionJob, source: str | Path, *, mode: str = "publish"
) -> DistributionResult:
    provider = provider_for(job.provider)
    source_path = Path(source).expanduser().resolve()
    existing = job_store().get(job.distribution_job_id)
    if existing and existing.state in {"PUBLISHED", "SCHEDULED", "DRAFTED"}:
        # Terminal success: never publish twice.  Still try to attach the
        # delivered artifact (read-only provider poll) so a replay returns the
        # same verifiable file/hash rather than a bare success.
        replayed: DistributionResult | None = None
        try:
            candidate = await provider.poll(existing)
            if candidate.success and candidate.artifact is not None:
                replayed = candidate
        except Exception:
            replayed = None
        if replayed is not None:
            return replayed.model_copy(
                update={
                    "provider_status": "idempotent_replay",
                    "message": "existing terminal success returned without duplicate publish",
                }
            )
        return DistributionResult(
            job=existing,
            provider_status="idempotent_replay",
            success=True,
            message="existing terminal success returned without duplicate publish",
        )
    if existing:
        job = existing
    job = job.model_copy(update={"state": "PUBLISHING"})
    job_store().put(job)
    if mode == "schedule":
        result = await provider.schedule(job, source_path)
    elif mode == "draft":
        result = await provider.save_draft(job, source_path)
    else:
        result = await provider.publish(job, source_path)
    job_store().put(result.job)
    return result
