"""Hevi unified capability registry package.

Importing this package auto-registers all built-in capabilities so that any
product line can resolve them by name via ``hevi.capabilities.get(name)``.
"""

from __future__ import annotations

# Auto-register built-in capabilities (order matters: definitions before registrars).
from . import handdraw
from .registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    get,
    list,
    names,
    register,
)

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "get",
    "list",
    "names",
    "register",
    "handdraw",
]
