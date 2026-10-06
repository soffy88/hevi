"""HEVI P8.2 — What was acquired, and how far the acquisition got.

Two things are kept apart here that are easy to conflate:

* :class:`AcquiredSource` — a located thing. It has a URI.
* :class:`AcquisitionEvidence` — proof the thing was actually obtained. It has a
  digest. (defined in ``hevi.evidence.acquisition``)

A URI is not evidence. It is a pointer that anyone can write, and a pipeline that
treats "we have a URL" as "we have the asset" never discovers that the URL 404s, was
never fetched, or was typed from memory. So :class:`AcquiredSource` requires an
``evidence_id``, and the acquisition path cannot reach ``ACQUIRED`` without bytes to
hash.

Acquisition state is also kept apart from execution state. ``ACQUIRED`` means the
bytes are here. ``PRODUCED`` means something was rendered, and that belongs to
``ExecutionReceipt`` in P6 — the same separation P7.3 froze for asset decisions, and
reasserted here because "we fetched the asset" is the newest way to accidentally claim
that something was produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AcquisitionState(StrEnum):
    """How far an acquisition got.

    Deliberately does not include ``PRODUCED``, ``QA_PASS`` or any other execution
    verdict. Getting the asset is not rendering it.

    The values are namespaced on purpose. ``RunState`` already contains a state called
    ``failed``, and a bare ``failed`` here would mean two different things in two
    layers — "the download did not complete" and "the render did not complete" — with
    no way to tell them apart after serialisation. The same reasoning P7.3 applied to
    ``AssetDecisionState`` applies here.
    """

    REQUESTED = "acquisition_requested"
    AVAILABLE = "acquisition_available"
    ACQUIRED = "acquired"
    FAILED = "acquisition_failed"


class AcquisitionFailure(StrEnum):
    """Why an acquisition did not complete.

    Split by cause rather than collapsed into ``FAILED``, because the causes need
    different responses and a single opaque failure hides all of them:

    * ``POLICY_BLOCKED`` — an authority said no. Retrying is pointless.
    * ``PROVIDER_UNREACHABLE`` — the observation layer already knows. Not a bug.
    * ``DOWNLOAD_FAILED`` — transport. Retrying may work.
    * ``CHECKSUM_MISMATCH`` — the payload is not what was expected. Retrying a
      tampered or truncated download without investigating is how bad data propagates.
    """

    POLICY_BLOCKED = "policy_blocked"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    DOWNLOAD_FAILED = "download_failed"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    EVIDENCE_MISSING = "evidence_missing"


@dataclass(frozen=True)
class AcquisitionRequest:
    """What was asked for, before anything was fetched."""

    request_id: str
    provider_id: str
    media_type: str
    source_id: str = ""
    intent: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("ACQUISITION_REQUEST_WITHOUT_ID:request_id required")
        if not self.provider_id:
            raise ValueError("ACQUISITION_REQUEST_WITHOUT_PROVIDER:provider_id required")
        if not self.media_type:
            raise ValueError("ACQUISITION_REQUEST_WITHOUT_MEDIA_TYPE:media_type required")
        if not self.source_id:
            raise ValueError(
                f"ACQUISITION_REQUEST_WITHOUT_SOURCE:{self.request_id}; the source "
                "this request may yield must be named up front, not invented later"
            )

    def locate(self) -> str:
        """Where this request's payload is expected to live."""
        return f"acquired://{self.provider_id}/{self.source_id}"


@dataclass(frozen=True)
class AcquiredSource:
    """A located thing that was actually obtained.

    Fields are exactly the P8.2 contract: identity, provider, location, digest, when,
    and the evidence that backs it. No provider facts — ``locality``,
    ``license_class`` and ``capabilities`` belong to ``ProviderProfile`` — and no
    execution verdict.
    """

    source_id: str
    provider_id: str
    uri: str
    checksum: str
    acquired_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    evidence_id: str = ""
    state: AcquisitionState = AcquisitionState.ACQUIRED

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("ACQUIRED_SOURCE_WITHOUT_ID:source_id required")
        if not self.provider_id:
            raise ValueError("ACQUIRED_SOURCE_WITHOUT_PROVIDER:provider_id required")
        if not self.uri:
            raise ValueError(
                f"ACQUIRED_SOURCE_WITHOUT_URI:{self.source_id}; a source must be locatable"
            )
        if not _is_sha256(self.checksum):
            raise ValueError(
                f"ACQUIRED_SOURCE_BAD_CHECKSUM:{self.source_id}:{self.checksum!r}; "
                "a source without a real digest is a claim, not a source"
            )
        if self.state is AcquisitionState.ACQUIRED and not self.evidence_id:
            raise ValueError(
                f"ACQUIRED_SOURCE_WITHOUT_EVIDENCE:{self.source_id}; ACQUIRED "
                "requires an evidence_id — a URI is not evidence"
            )
        if not isinstance(self.state, AcquisitionState):
            raise ValueError(f"UNKNOWN_ACQUISITION_STATE:{self.state!r}")

    @property
    def is_acquired(self) -> bool:
        return self.state is AcquisitionState.ACQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "provider_id": self.provider_id,
            "uri": self.uri,
            "checksum": self.checksum,
            "acquired_at": self.acquired_at.isoformat(),
            "evidence_id": self.evidence_id,
            "state": self.state.value,
        }


@dataclass(frozen=True)
class AcquisitionOutcome:
    """The result of one attempt: a source, or a reason there is none.

    Always one of the two, never both. An outcome carrying a source *and* a failure
    would let a caller read whichever field it found convenient.
    """

    request_id: str
    provider_id: str
    source: AcquiredSource | None = None
    failure: AcquisitionFailure | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("ACQUISITION_OUTCOME_WITHOUT_ID:request_id required")
        if (self.source is None) == (self.failure is None):
            raise ValueError(
                f"AMBIGUOUS_ACQUISITION_OUTCOME:{self.request_id}; exactly one of "
                "source or failure must be set"
            )
        if self.failure is not None and not isinstance(self.failure, AcquisitionFailure):
            raise ValueError(f"UNKNOWN_ACQUISITION_FAILURE:{self.failure!r}")
        if self.failure is not None and not self.reason:
            raise ValueError(
                f"ACQUISITION_FAILURE_WITHOUT_REASON:{self.request_id}; a failure "
                "must be explicable"
            )
        if self.source is not None and self.source.provider_id != self.provider_id:
            raise ValueError(
                f"ACQUISITION_OUTCOME_PROVIDER_MISMATCH:{self.request_id}; the source "
                f"came from {self.source.provider_id}, not {self.provider_id}"
            )

    @property
    def succeeded(self) -> bool:
        return self.source is not None and self.source.is_acquired

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider_id": self.provider_id,
            "source": self.source.to_dict() if self.source else None,
            "failure": self.failure.value if self.failure else None,
            "reason": self.reason,
        }


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


__all__ = [
    "AcquiredSource",
    "AcquisitionFailure",
    "AcquisitionOutcome",
    "AcquisitionRequest",
    "AcquisitionState",
]
