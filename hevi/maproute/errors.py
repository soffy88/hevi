"""Map-route line errors."""

from __future__ import annotations


class MapRouteError(RuntimeError):
    """Raised for any map-route failure (geocode / route / render).

    The capability wrapper converts this into ``CapabilityError`` so a
    failed render never surfaces as a fake success (CAPABILITY_CONTRACT).
    """


__all__ = ["MapRouteError"]
