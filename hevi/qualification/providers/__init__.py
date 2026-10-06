"""HEVI P9.1.d.1 — per-provider qualification adapters.

One adapter per local provider. Each one **executes**; none of them **judges**. The
verdict is the framework's, and it is reached by reading the bytes, computing the
digest, issuing a receipt and running P8.4 validation.

An :class:`ExecutionResult` has no field in which to return a verdict, so
``return QUALIFIED`` is not merely discouraged — it is inexpressible.
"""

from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    ProviderQualification,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers.ffmpeg import FfmpegAdapter
from hevi.qualification.providers.html_gsap import HtmlGsapAdapter
from hevi.qualification.providers.hyperframes import HyperframesAdapter
from hevi.qualification.providers.manim import ManimAdapter
from hevi.qualification.providers.remotion import RemotionAdapter

#: Every local provider, and the adapter that can execute it. Keyed by provider id, so
#: the framework never switches on a provider name to find a driver.
ADAPTERS: dict[str, type] = {
    "manim": ManimAdapter,
    "remotion": RemotionAdapter,
    "hyperframes": HyperframesAdapter,
    "html_gsap": HtmlGsapAdapter,
    "ffmpeg": FfmpegAdapter,
}

__all__ = [
    "ADAPTERS",
    "AdapterAvailability",
    "AdapterFailure",
    "Availability",
    "ExecutionResult",
    "ExecutionState",
    "FfmpegAdapter",
    "HtmlGsapAdapter",
    "HyperframesAdapter",
    "ManimAdapter",
    "ProviderQualification",
    "QualificationRequest",
    "RemotionAdapter",
    "RuntimeUnavailable",
    "adapter_for",
]


def adapter_for(provider_id: str) -> type | None:
    """The adapter for a provider, or ``None`` if none can execute it."""
    return ADAPTERS.get(provider_id)
