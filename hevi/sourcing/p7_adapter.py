"""P7 adapter — translate an ``AssetRequirement`` into sourcing's own requests.

The only file P7 adds inside ``hevi/sourcing``. Nothing else in sourcing is
rewritten, and this module imports *no* P7 type at runtime — the requirement is
accepted structurally — so sourcing remains usable without P7 installed.

Why an adapter at all
---------------------
``StockSearchService.search`` takes ``query: str, media_type: str, count: int`` and
only understands ``"image"`` and ``"video"`` lowercase.
``AssetRequirement`` speaks ``MediaType.IMAGE``/``VIDEO`` plus a narrative role, a
quality floor and source terms. Translating between them is a real, small
boundary, and putting it here keeps sourcing's API stable while P7 evolves.

The mapping is a lookup table, not a branch
-------------------------------------------
``_MEDIA_TYPE_TO_SOURCING`` is the whole conversion. There is no
``if media_type == "IMAGE":`` dispatch and no product awareness; the requirement
never names a vendor, so this module cannot acquire from one it was told to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: P7 MediaType -> sourcing's stock-search vocabulary. Sourcing supports image and
#: video only; every other representation is unservable *by the stock path*, which is
#: a fact about sourcing's capability, not a judgement about the requirement.
_MEDIA_TYPE_TO_SOURCING: dict[str, str] = {
    "IMAGE": "image",
    "VIDEO": "video",
}

#: P7 MediaType -> the media_providers.default_providers() key that serves it.
_MEDIA_TYPE_TO_PROVIDER_KEY: dict[str, str] = {
    "IMAGE": "image",
    "VIDEO": "video",
    "AUDIO": "voice",
    "TEXTURE": "lut",
    "DOCUMENT": "document",
}

#: Representations sourcing has no provider for. Surfaced as a reason rather than
#: silently dropped, so a blocked requirement says why.
UNSERVABLE_MEDIA_TYPES: frozenset[str] = frozenset({"MODEL3D"})


@dataclass(frozen=True)
class StockSearchRequest:
    """Ready to hand to ``StockSearchService.search``."""

    query: str
    media_type: str
    count: int
    semantic_role: str
    servable: bool = True
    reason: str = ""

    def as_search_kwargs(self, *, user_id: str) -> dict[str, Any]:
        """The exact kwargs ``StockSearchService.search`` expects."""
        if not self.servable:
            raise ValueError(f"UNSERVABLE_MEDIA_TYPE:{self.reason or self.media_type}")
        return {
            "user_id": user_id,
            "query": self.query,
            "media_type": self.media_type,
            "count": self.count,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "media_type": self.media_type,
            "count": self.count,
            "semantic_role": self.semantic_role,
            "servable": self.servable,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MediaProviderRequest:
    """Which ``media_providers`` key can serve this requirement, and why not."""

    provider_key: str
    semantic_role: str
    servable: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_key": self.provider_key,
            "semantic_role": self.semantic_role,
            "servable": self.servable,
            "reason": self.reason,
        }


def to_stock_request(requirement: Any) -> StockSearchRequest:
    """Translate a requirement into a stock search request.

    Reads ``media_type``, ``semantic_role``, ``quantity``, ``constraint_map()`` and
    ``query()`` structurally, so a duck-typed requirement works and no P7 import is
    required.
    """
    media_type = str(getattr(requirement.media_type, "value", requirement.media_type))
    role = str(getattr(requirement.semantic_role, "value", requirement.semantic_role))
    count = int(getattr(requirement, "quantity", 1))
    query = requirement.query()

    if media_type in UNSERVABLE_MEDIA_TYPES:
        return StockSearchRequest(
            query=query, media_type=media_type, count=count, semantic_role=role,
            servable=False, reason=f"no sourcing provider for {media_type}",
        )
    mapped = _MEDIA_TYPE_TO_SOURCING.get(media_type)
    if mapped is None:
        return StockSearchRequest(
            query=query, media_type=media_type, count=count, semantic_role=role,
            servable=False, reason=f"stock path does not serve {media_type}",
        )
    return StockSearchRequest(
        query=query, media_type=mapped, count=count, semantic_role=role,
        servable=True,
    )


def to_media_request(requirement: Any) -> MediaProviderRequest:
    """Translate a requirement into a media-provider request."""
    media_type = str(getattr(requirement.media_type, "value", requirement.media_type))
    role = str(getattr(requirement.semantic_role, "value", requirement.semantic_role))
    key = _MEDIA_TYPE_TO_PROVIDER_KEY.get(media_type)
    if key is None:
        return MediaProviderRequest(
            provider_key="", semantic_role=role,
            servable=False, reason=f"no media provider for {media_type}",
        )
    return MediaProviderRequest(provider_key=key, semantic_role=role, servable=True)


def media_type_to_sourcing(value: str) -> str:
    """Single spelling conversion, exposed for callers that need it directly."""
    return _MEDIA_TYPE_TO_SOURCING[value]


__all__ = [
    "UNSERVABLE_MEDIA_TYPES",
    "MediaProviderRequest",
    "StockSearchRequest",
    "media_type_to_sourcing",
    "to_media_request",
    "to_stock_request",
]
