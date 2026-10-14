"""Hevi unified capability contract and registry."""

from .registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    get,
    list_capabilities,
    register,
)

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "register",
    "get",
    "list_capabilities",
]
