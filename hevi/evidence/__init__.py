"""HEVI P8.2 — Acquisition evidence.

Evidence proves that specific bytes were obtained from a specific provider at a
specific time. It does not prove quality, licensing, or policy approval — those
belong to the catalogue and to ``ProviderPolicy``.
"""

from hevi.evidence.acquisition import (
    AcquisitionEvidence,
    AcquisitionMethod,
    checksum_bytes,
)

__all__ = ["AcquisitionEvidence", "AcquisitionMethod", "checksum_bytes"]
