"""HEVI P9.1.c — Remotion as a first-class provider.

``provider`` declares who Remotion is; ``driver`` executes a render and returns a
locator. Neither hashes, probes, validates or decides — those belong to P8.2, P8.3 and
P8.4, and the audit finding R1 was that the legacy renderer did all of them itself.

The catalogue entry itself lives in ``hevi/providers/facts.py``; this package holds the
provider-specific declaration and the driver.
"""

from hevi.providers.remotion.driver import (
    RemotionUnavailable,
    RenderLocator,
    compositions,
    is_available,
    probe_runtime,
    project_dir,
    render,
    render_remotion,
)
from hevi.providers.remotion.provider import (
    PROVIDER_ID,
    declaration,
    profile,
)

__all__ = [
    "PROVIDER_ID",
    "RemotionUnavailable",
    "RenderLocator",
    "compositions",
    "declaration",
    "is_available",
    "probe_runtime",
    "profile",
    "project_dir",
    "render",
    "render_remotion",
]
