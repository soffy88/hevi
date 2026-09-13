"""Optional semantic provider boundary; no fake visual understanding."""

from __future__ import annotations


class SemanticProviderUnavailable(RuntimeError):
    """No configured provider can inspect visual frames."""


def semantic_provider_status() -> str:
    return "BLOCKED_PROVIDER"
