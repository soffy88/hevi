"""HEVI P7.0 — The asset contract: two vocabularies, deliberately separate.

This module exists because ``hevi.sourcing`` and P6 could not talk. Sourcing has a
**narrative role** taxonomy; P7 needed a **media representation** taxonomy. Neither
was wrong, and neither replaces the other:

* :class:`AssetSemanticRole` — what an asset is *for*. Values are derived from
  ``hevi.sourcing.loader_bridge.ASSET_TYPES`` and are the existing owner of that
  idea. Not redefined here.
* :class:`MediaType` — what an asset *is*, as delivered. New in P7, because no
  representation vocabulary existed anywhere.

A requirement names both, and they never substitute for each other:

    historical portrait   -> media_type=IMAGE   semantic_role=CHARACTER
    documentary field     -> media_type=VIDEO   semantic_role=SCENE
    narration             -> media_type=AUDIO   semantic_role=VOICE

Why this matters
----------------
P6.5.2 collapsed its compatibility matrix to a diagonal because two layers each
owned one vocabulary and demanded identity. Here the two axes are orthogonal by
construction and a test (``test_media_type_is_never_a_semantic_role``) asserts the
sets are disjoint — so the same mistake cannot be reintroduced by relaxing a check.

What this module does not do
----------------------------
It defines no registry, repository, store, validator or provider. Those belong to
``hevi.sourcing``. It describes assets; it never acquires, downloads, ranks or
selects one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.sourcing.loader_bridge import ASSET_TYPES as _SOURCING_ASSET_TYPES


class MediaType(StrEnum):
    """Media representation. New in P7; no equivalent existed."""

    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    MODEL3D = "MODEL3D"
    TEXTURE = "TEXTURE"
    DOCUMENT = "DOCUMENT"


class AssetSemanticRole(StrEnum):
    """Narrative role. Derived from ``hevi.sourcing``'s own taxonomy.

    Sourcing stores these lowercase because they are its storage keys; P7 presents
    them as a closed vocabulary. :meth:`sourcing_key` is the only sanctioned way
    back to the owner's spelling, so the two cannot drift.
    """

    CHARACTER = "CHARACTER"
    SCENE = "SCENE"
    VOICE = "VOICE"
    PROP = "PROP"
    FX = "FX"

    @classmethod
    def from_sourcing(cls, value: str) -> AssetSemanticRole:
        return cls[value.upper()]

    def sourcing_key(self) -> str:
        return self.value.lower()


class AssetOrigin(StrEnum):
    """Where an asset would come from."""

    LOCAL_GENERATED = "LOCAL_GENERATED"
    EXTERNAL_SOURCE = "EXTERNAL_SOURCE"
    UNKNOWN = "UNKNOWN"


class AssetStatus(StrEnum):
    """Availability. The safe default is refusal, never availability."""

    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


#: The owner's taxonomy, asserted equal to the enum's members by test.
SOURCING_ASSET_TYPES: frozenset[str] = frozenset(_SOURCING_ASSET_TYPES)


@dataclass(frozen=True)
class AssetReference:
    """A pointer to an asset. A description, never a downloaded thing.

    No ``local_path``, no ``download()``, no ``fetch()``: P7 does not acquire.
    """

    asset_id: str
    media_type: MediaType
    semantic_role: AssetSemanticRole
    origin: AssetOrigin = AssetOrigin.UNKNOWN
    status: AssetStatus = AssetStatus.REJECTED
    uri: str = ""
    provider_id: str = ""
    license: str = ""
    metadata: tuple[tuple[str, str], ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("ASSET_REFERENCE_WITHOUT_ID:asset_id required")
        for label, value, vocabulary in (
            ("media_type", self.media_type, MediaType),
            ("semantic_role", self.semantic_role, AssetSemanticRole),
            ("origin", self.origin, AssetOrigin),
            ("status", self.status, AssetStatus),
        ):
            if not isinstance(value, vocabulary):
                raise ValueError(f"UNKNOWN_{label.upper()}:{value!r}")
        if self.status is AssetStatus.BLOCKED and not self.reason:
            raise ValueError(
                f"BLOCKED_ASSET_WITHOUT_REASON:{self.asset_id}; a blocked asset must "
                "say why, so absence is visible rather than silent"
            )

    def metadata_map(self) -> dict[str, str]:
        return dict(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "media_type": self.media_type.value,
            "semantic_role": self.semantic_role.value,
            "origin": self.origin.value,
            "status": self.status.value,
            "uri": self.uri,
            "provider_id": self.provider_id,
            "license": self.license,
            "metadata": dict(self.metadata),
            "reason": self.reason,
        }

    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "SOURCING_ASSET_TYPES",
    "AssetOrigin",
    "AssetReference",
    "AssetSemanticRole",
    "AssetStatus",
    "MediaType",
]
