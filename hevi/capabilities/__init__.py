"""Hevi unified capability registry — public surface.

Importing this package must NOT trigger heavy side effects (no chromium
launch, no ffmpeg).  Capability *registration* is explicit via
:func:`hevi.capabilities.scene3d.register_scene3d_capabilities`, called by the
line's bootstrap so the catalogue is populated lazily and testably.
"""

from __future__ import annotations

from .errors import CapabilityError
from .registry import (
    Capability,
    Registry,
    contains,
    get,
    list,
    list_capabilities,
    register,
    resolve,
)
from .result import CapabilityResult

# Auto-register the bundled capability families on import (cheap, side-effect
# free: no chromium / ffmpeg is launched here, only dataclass wiring).  Any
# product line importing ``hevi.capabilities`` can immediately call
# ``hevi.capabilities.get("scene3d.planet_orbit")``.
from . import scene3d as _scene3d  # noqa: E402,F401
_scene3d.register_scene3d_capabilities_once()
from . import svfactory as _svfactory  # noqa: E402,F401

# Kids / anime safety gates (``qa.kids_gate``, ``kids.story_gate``,
# ``kids.consistency_manifest``) are registered by importing the registry.
# ``registry.register`` is import-triggered for these three so every line can
# resolve them by name without extra wiring.

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "register",
    "get",
    "resolve",
    "list",
    "list_capabilities",
    "contains",
    "Registry",
]
