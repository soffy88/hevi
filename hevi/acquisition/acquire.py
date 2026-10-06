"""HEVI P8.2 — The acquisition path, and the three gates it passes through.

An acquired source is the first thing in the chain that rests on bytes rather than on
a claim, so this is where the shortcuts are most tempting. Three gates, in order:

    ProviderDecision  — may this provider be used at all?
    ProviderRuntimeStatus — is it answering right now?
    payload           — did anything actually arrive, and is it what we expect?

Each gate can stop the acquisition, and each stops it for its own reason. That matters
because collapsing them produces the failure P8 exists to prevent: a source that was
never fetched, reported as acquired, because the URL was well-formed.

No network client lives here. This module is the *gating and bookkeeping* around a
fetch; how bytes are obtained is the provider's business, and a second fetcher would be
a fork of the same kind P8.1 avoided with probes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from hevi.acquisition.models import (
    AcquiredSource,
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionRequest,
    AcquisitionState,
)
from hevi.evidence.acquisition import (
    AcquisitionEvidence,
    AcquisitionMethod,
    checksum_bytes,
)
from hevi.runtime.provider.models import ProviderRuntimeStatus

#: Produces the payload for a request. Injected, so qualification can run without a
#: network and so the fetcher stays the provider's concern rather than this module's.
Fetcher = Callable[[AcquisitionRequest], bytes]


def _failure(
    request: AcquisitionRequest,
    failure: AcquisitionFailure,
    reason: str,
    *,
    checked_at: datetime | None = None,
) -> AcquisitionOutcome:
    return AcquisitionOutcome(
        request_id=request.request_id,
        provider_id=request.provider_id,
        failure=failure,
        reason=reason,
    )


def _blocked_by_policy(request: AcquisitionRequest) -> AcquisitionOutcome:
    return _failure(
        request,
        AcquisitionFailure.POLICY_BLOCKED,
        "provider was not selected by ProviderPolicy",
    )


def _blocked_by_runtime(
    request: AcquisitionRequest, status: ProviderRuntimeStatus
) -> AcquisitionOutcome:
    return _failure(
        request,
        AcquisitionFailure.PROVIDER_UNREACHABLE,
        status.failure_reason or f"runtime availability is {status.availability.value}",
    )


def acquire(
    request: AcquisitionRequest,
    *,
    eligible: bool,
    status: ProviderRuntimeStatus | None,
    fetch: Fetcher,
    expected_checksum: str | None = None,
    method: AcquisitionMethod = AcquisitionMethod.HTTP_FETCH,
    evidence_id: str | None = None,
    uri: str | None = None,
    checked_at: datetime | None = None,
) -> AcquisitionOutcome:
    """Acquire one source, or explain why not.

    Returns an :class:`AcquisitionOutcome` rather than raising for ordinary failure:
    an unreachable provider or a short read is a result, not an exception. Programming
    errors still raise.
    """
    moment = checked_at or datetime.now(UTC)

    if not eligible:
        return _blocked_by_policy(request)

    # A missing status is UNKNOWN, which is not usable — the same fail-closed rule
    # P8.1 established, applied here so "we never looked" cannot acquire anything.
    observed = status or ProviderRuntimeStatus(provider_id=request.provider_id)
    if not observed.is_usable:
        return _blocked_by_runtime(request, observed)

    try:
        payload = fetch(request)
    except Exception as exc:
        return _failure(
            request,
            AcquisitionFailure.DOWNLOAD_FAILED,
            f"{type(exc).__name__}:{exc}",
            checked_at=moment,
        )

    if not payload:
        return _failure(
            request,
            AcquisitionFailure.DOWNLOAD_FAILED,
            "fetcher returned an empty payload",
            checked_at=moment,
        )

    digest = checksum_bytes(payload)
    if expected_checksum is not None and digest != expected_checksum:
        return _failure(
            request,
            AcquisitionFailure.CHECKSUM_MISMATCH,
            f"expected {expected_checksum}, got {digest}",
            checked_at=moment,
        )

    # Evidence and source are minted together, from the same payload. There is no code
    # path that produces one without the other, which is what makes "ACQUIRED" mean
    # something a URI could not have meant.
    resolved_evidence_id = evidence_id or f"ev-{request.request_id}"
    evidence = AcquisitionEvidence(
        evidence_id=resolved_evidence_id,
        provider_id=request.provider_id,
        source_id=request.source_id,
        checksum=digest,
        timestamp=moment,
        acquisition_method=method,
    )
    source = AcquiredSource(
        source_id=request.source_id,
        provider_id=request.provider_id,
        uri=uri or request.locate(),
        checksum=digest,
        acquired_at=moment,
        evidence_id=evidence.evidence_id,
        state=AcquisitionState.ACQUIRED,
    )
    return AcquisitionOutcome(
        request_id=request.request_id,
        provider_id=request.provider_id,
        source=source,
    )


def verify_outcome(
    outcome: AcquisitionOutcome, payload: bytes, evidence: AcquisitionEvidence
) -> bool:
    """Whether the outcome, the evidence and the bytes all tell the same story.

    The end-to-end check: three records that agree, plus a digest computed from the
    payload rather than copied from any of them.
    """
    source = outcome.source
    if source is None:
        return False
    return (
        evidence.verify_against(payload)
        and evidence.matches(source.provider_id, source.source_id, source.checksum)
        and source.evidence_id == evidence.evidence_id
    )


__all__ = ["Fetcher", "acquire", "verify_outcome"]
