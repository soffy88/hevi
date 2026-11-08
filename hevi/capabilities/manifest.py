"""3O manifest for the capabilities registry (SPEC §2.5).

The registry package exposes ``__manifest__``: the element list with
layer attribution, render signature, and version, for catalogue queries
and reuse decisions. Built lazily after all registrations (the tail of
``hevi/capabilities/__init__.py`` calls :func:`build_manifest`), so the
manifest always reflects the live registry.
"""

from __future__ import annotations

import inspect
from typing import Any

MANIFEST_VERSION = "1.0.0"
MANIFEST_SPEC = "HELIOS_3O_SPEC_v3_0"


def build_manifest(capabilities: Any) -> dict[str, Any]:
    """Build the manifest dict from the live registry contents.

    ``capabilities`` is the iterable of :class:`Capability` objects
    (pass ``list_capabilities()`` from the registry).
    """
    elements: list[dict[str, Any]] = []
    for cap in capabilities:
        try:
            signature = str(inspect.signature(cap.render))
        except (TypeError, ValueError):
            signature = "unknown"
        elements.append(
            {
                "name": cap.name,
                "layer": cap.layer,
                "kind": cap.kind,
                "line": cap.line,
                "signature": signature,
                "version": getattr(cap.render, "__version__", "unversioned"),
            }
        )
    elements.sort(key=lambda item: item["name"])
    return {
        "spec": MANIFEST_SPEC,
        "version": MANIFEST_VERSION,
        "elements": elements,
        "count": len(elements),
    }
