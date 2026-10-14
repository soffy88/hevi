"""Hevi unified capability registry.

Every product line (zero, talkcraft, short-drama, artmotion, explainer,
ShotSpec workbench, …) must expose its generative abilities through this one
registry, addressed by a stable dotted name (``scene3d.planet_orbit``,
``handdraw.narration``, …).  No line is allowed to keep a private entry point:
see ``CAPABILITY_CONTRACT.md`` (user addendum 2026-10-14).

The contract requires these primitives:

* ``register(Capability(...))`` — install a capability.
* ``get(name)`` — resolve a capability by name (raises ``CapabilityError``).
* ``list(kind=..., aspect=...)`` — enumerate registered capabilities.
* ``Capability.render(params, out_dir, *, duration, aspect, seed)`` — produce
  the artefact (mp4/png/wav) deterministically and return a
  ``CapabilityResult``.  A failed render raises ``CapabilityError``; it must
  never return a fake success.

The scene3d line (``hevi/layer4_legacy/scene3d``) is the first consumer that
registers itself here.  ``webkit`` owns the authoritative registry at merge
time; this branch's implementation is the minimal contract surface agreed in
``CAPABILITY_CONTRACT.md`` and is merge-compatible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CapabilityError
from .result import CapabilityResult

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "register",
    "get",
    "list_capabilities",
    "list",
    "resolve",
    "Registry",
]

# Canonical registry: a process-global, ordered dict keyed by capability name.
_REGISTRY: dict[str, "Capability"] = {}


@dataclass
class Capability:
    """A named, product-line-agnostic generative ability.

    A capability renders an artefact (mp4 / png / wav) deterministically for a
    given ``seed`` and reports the result via :class:`CapabilityResult`.
    """

    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: list[str]  # e.g. ["16:9", "9:16"]
    params_schema: dict[str, Any]
    cpu_cost_hint: float  # approx CPU-seconds per second of output video
    render: Any  # callable(params, out_dir, *, duration, aspect, seed) -> CapabilityResult
    description: str = ""
    line: str = ""  # owning product line (e.g. "scene3d")

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate ``params`` against ``params_schema``; return the params.

        Raises :class:`CapabilityError` on any schema violation.  When a JSON
        schema validator is unavailable the params are returned unchanged so a
        capability is still callable in minimal environments.
        """
        try:
            import jsonschema
        except Exception:  # pragma: no cover - jsonschema is always present in CI.
            return params
        try:
            jsonschema.validate(instance=params, schema=self.params_schema)
        except Exception as exc:  # jsonschema.ValidationError subclasses Exception.
            raise CapabilityError(
                f"capability {self.name}: invalid params: {exc}"
            ) from exc
        return params

    def supports_aspect(self, aspect: str) -> bool:
        return aspect in self.aspects


def register(cap: Capability) -> Capability:
    """Install ``cap`` into the global registry (last writer wins per name)."""
    if not cap.name:
        raise CapabilityError("capability name must be non-empty")
    _REGISTRY[cap.name] = cap
    return cap


def contains(name: str) -> bool:
    """Whether a capability is currently registered."""
    return name in _REGISTRY


def get(name: str) -> Capability:
    """Resolve a capability by name; raise :class:`CapabilityError` if absent."""
    cap = _REGISTRY.get(name)
    if cap is None:
        raise CapabilityError(f"unknown capability: {name!r}")
    return cap


def resolve(name: str) -> Capability:
    """Alias of :func:`get` (ShotSpec-style naming)."""
    return get(name)


def list_capabilities(
    kind: str | None = None, aspect: str | None = None
) -> list[Capability]:
    """Enumerate registered capabilities, optionally filtered by kind/aspect."""
    out: list[Capability] = []
    for cap in _REGISTRY.values():
        if kind is not None and cap.kind != kind:
            continue
        if aspect is not None and aspect not in cap.aspects:
            continue
        out.append(cap)
    return out


# Public alias matching the contract's ``list(kind=..., aspect=...)`` signature.
list = list_capabilities  # noqa: A001 - intentionally mirrors the contract API.


def Registry() -> dict[str, Capability]:  # noqa: N802 - DDD-style factory per contract.
    """Return the live registry mapping (read-only intent; do not mutate)."""
    return dict(_REGISTRY)


def _summary() -> list[dict[str, Any]]:
    """Machine-readable inventory for the API capability listing."""
    return [
        {
            "name": c.name,
            "kind": c.kind,
            "aspects": c.aspects,
            "line": c.line,
            "cpu_cost_hint": c.cpu_cost_hint,
            "description": c.description,
        }
        for c in _REGISTRY.values()
    ]


def export_catalogue(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Write ``docs/generated/capability_catalogue.json`` and return it."""
    data = _summary()
    if path is None:
        path = Path(__file__).resolve().parents[2] / "docs" / "generated" / "capability_catalogue.json"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
