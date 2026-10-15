"""Capability errors.

A capability render failure or resolution failure must surface as
``CapabilityError`` — never as a silent success (contract: "失败时抛
CapabilityError，不允许返回假成功").
"""

from __future__ import annotations


class CapabilityError(RuntimeError):
    """Raised when a capability is unknown, mis-parametrised, or fails to render."""


__all__ = ["CapabilityError"]
