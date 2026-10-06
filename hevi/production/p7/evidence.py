"""HEVI P7.0 — Asset evidence: the auditable record of an obtained asset.

Commercial production needs to answer, for every asset that reached a render: what
was it, where did it come from, under what licence, did it pass validation, and
is it still the same bytes. That is this record.

It is deliberately narrow. P7 records; ``hevi.sourcing`` acquires and validates.
``validation`` carries a summarisation of sourcing's ``AssetVerdict`` — P7 imports
neither the verdict class nor the validator, so it cannot become a second quality
gate, and a change to sourcing's validation rules cannot silently diverge here.

``retrieval_time`` is recorded but excluded from :meth:`fingerprint`, for the same
reason P5.3's evidence excludes ``timestamp``: a fact that hashes differently on
every run cannot be diffed or compared between runs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from hevi.production.p7.asset_contract import AssetStatus


@dataclass(frozen=True)
class AssetEvidence:
    """One auditable fact about one obtained asset."""

    asset_id: str
    source: str
    status: AssetStatus = AssetStatus.REJECTED
    license: str = ""
    validation: str = ""
    retrieval_time: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("ASSET_EVIDENCE_WITHOUT_ID:asset_id required")
        if not self.source:
            raise ValueError("ASSET_EVIDENCE_WITHOUT_SOURCE:source required")
        if not isinstance(self.status, AssetStatus):
            raise ValueError(f"UNKNOWN_ASSET_STATUS:{self.status!r}")
        # An asset that claims to be available must say where it came from and
        # under what terms. Otherwise the licence claim is unfalsifiable.
        if self.status is AssetStatus.AVAILABLE and not self.license:
            raise ValueError(
                f"AVAILABLE_ASSET_WITHOUT_LICENSE:{self.asset_id}; an available asset "
                "must declare its licence, so commercial terms stay auditable"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "source": self.source,
            "status": self.status.value,
            "license": self.license,
            "validation": self.validation,
            "retrieval_time": self.retrieval_time,
            "content_hash": self.content_hash,
        }

    def fingerprint(self) -> str:
        """Stable fingerprint. ``retrieval_time`` is excluded by construction."""
        payload = {k: v for k, v in self.to_dict().items() if k != "retrieval_time"}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["AssetEvidence"]
