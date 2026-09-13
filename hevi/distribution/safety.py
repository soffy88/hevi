from __future__ import annotations

import hashlib
from pathlib import Path

from hevi.distribution.models import DistributionJob


class DistributionSafetyError(RuntimeError):
    pass


def verify_publishable_source(
    source: str | Path,
    *,
    expected_sha256: str,
    quality_passed: bool,
) -> str:
    """Require an existing, immutable, quality-approved source artifact."""

    path = Path(source).expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise DistributionSafetyError("UPLOAD_FAILURE: source artifact is absent or empty")
    if not quality_passed:
        raise DistributionSafetyError("QUALITY_GATE_FAILED: artifact is not approved")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise DistributionSafetyError("PROVENANCE_INCOMPLETE: source sha256 mismatch")
    return digest


def ambiguous_publish(job: DistributionJob, reason: str) -> DistributionJob:
    """Never retry an unknown provider side effect automatically."""

    return job.model_copy(
        update={"state": "NEEDS_ATTENTION", "failure_class": reason}
    )
