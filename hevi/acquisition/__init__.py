"""HEVI P8.2 — Acquisition: provider output becomes a located, evidenced source.

The boundary this package holds: a URI is not evidence. An acquired source carries
a digest and an ``evidence_id``; reaching ``ACQUIRED`` requires bytes to hash.

Acquisition state and execution state are disjoint. Getting the asset is not
rendering it, and only ``ExecutionReceipt`` may say something was produced.
"""

from hevi.acquisition.acquire import Fetcher, acquire, verify_outcome
from hevi.acquisition.models import (
    AcquiredSource,
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionRequest,
    AcquisitionState,
)

__all__ = [
    "AcquiredSource",
    "AcquisitionFailure",
    "AcquisitionOutcome",
    "AcquisitionRequest",
    "AcquisitionState",
    "Fetcher",
    "acquire",
    "verify_outcome",
]
