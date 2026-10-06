"""HEVI P8.2 — Acquisition evidence.

P7 established that an asset id is a string and that a claim about it needs evidence.
P8.2 applies the same discipline to *acquisition*, where the failure is more seductive:
a URI looks like proof. It is not. A URI is an assertion by whoever typed it, and the
cheapest possible fake acquisition is a well-formed https link.

What makes evidence different is that it commits to bytes:

    uri ──fetch──▶ bytes ──sha256──▶ checksum
                                        +
                              the event that fetched them
                                        =
                                   evidence

The checksum cannot be typed from imagination — it is a function of the payload. So
evidence is falsifiable in a way a URI is not, and :class:`AcquisitionEvidence` holds
a checksum rather than a location.

What evidence proves, precisely
------------------------------
It proves *this source was produced by this provider, by this method, at this time,
and these bytes hash to this value.*

It does **not** prove:

* that the content is any good — quality is not evidence
* that it is lawful to use — licensing is a declared fact, from the catalogue
* that policy approved it — eligibility is ``ProviderDecision``'s business
* that it will still be there tomorrow — a URI is not a lease

Overclaiming here is how a provenance system turns into a compliance system without
anyone noticing. Evidence is narrower than all four, deliberately.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

#: A sha256 digest in lowercase hex.
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def checksum_bytes(payload: bytes) -> str:
    """The digest that makes an acquisition falsifiable.

    Everything else in this module is a claim someone typed. This is a claim the
    payload itself makes.
    """
    return hashlib.sha256(payload).hexdigest()


class AcquisitionMethod(StrEnum):
    """How the bytes were obtained.

    Recorded because "we have it" and "we fetched it from the provider we said" are
    different claims, and a cache hit or a fixture masquerading as a fetch is exactly
    the kind of substitution that a provenance record exists to expose.
    """

    HTTP_FETCH = "http_fetch"
    QUEUE_POLL = "queue_poll"
    LOCAL_READ = "local_read"
    API_RESPONSE = "api_response"


@dataclass(frozen=True)
class AcquisitionEvidence:
    """Proof that a specific payload was obtained from a specific provider.

    Carries no URI. A locator can be copied, forged or expire; a digest cannot be
    forged without the bytes, which is the entire reason this type exists separately
    from :class:`~hevi.acquisition.models.AcquiredSource`.
    """

    evidence_id: str
    provider_id: str
    source_id: str
    checksum: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    acquisition_method: AcquisitionMethod = AcquisitionMethod.HTTP_FETCH

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("ACQUISITION_EVIDENCE_WITHOUT_ID:evidence_id required")
        if not self.provider_id:
            raise ValueError("ACQUISITION_EVIDENCE_WITHOUT_PROVIDER:provider_id required")
        if not self.source_id:
            raise ValueError("ACQUISITION_EVIDENCE_WITHOUT_SOURCE:source_id required")
        if not _SHA256_HEX.match(self.checksum or ""):
            raise ValueError(
                f"ACQUISITION_EVIDENCE_BAD_CHECKSUM:{self.checksum!r}; expected a "
                "sha256 hex digest of the payload, not a placeholder"
            )
        if not isinstance(self.acquisition_method, AcquisitionMethod):
            raise ValueError(
                f"UNKNOWN_ACQUISITION_METHOD:{self.acquisition_method!r}"
            )

    def matches(self, provider_id: str, source_id: str, checksum: str) -> bool:
        """Whether this evidence supports exactly that claim."""
        return (
            self.provider_id == provider_id
            and self.source_id == source_id
            and self.checksum == checksum
        )

    def verify_against(self, payload: bytes) -> bool:
        """Whether the recorded digest is the digest of these bytes.

        The only check in P8.2 that cannot be satisfied by typing.
        """
        return self.checksum == checksum_bytes(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "provider_id": self.provider_id,
            "source_id": self.source_id,
            "checksum": self.checksum,
            "timestamp": self.timestamp.isoformat(),
            "acquisition_method": self.acquisition_method.value,
        }


__all__ = [
    "AcquisitionEvidence",
    "AcquisitionMethod",
    "checksum_bytes",
]
