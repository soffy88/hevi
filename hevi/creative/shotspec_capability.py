"""ShotSpec ↔ unified capability bridge.

Implements the ``CAPABILITY_CONTRACT.md``接入点::

    shot_spec.capability = {"name": ..., "params": {...}}
    assemble 按名字调用；名字不存在就返回 422.

This is the minimal integration the contract requires: a ShotSpec may bind a
registered capability by name, and :func:`assemble_shot` renders it through the
registry.  An unknown name (or a params/aspect that the capability rejects)
surfaces as :class:`ShotCapabilityError` with ``status_code = 422`` so an HTTP
layer can map it directly; genuine render failures stay 500-class.

It deliberately does *not* duplicate the renderer or the registry — it is a thin
projection so ShotSpec consumers (assemble, workbench, webkit) share one path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.capabilities import CapabilityError, CapabilityResult, get

from .director_contract import ShotSpec

__all__ = ["ShotCapabilityError", "assemble_shot", "resolve_shot_capability"]


class ShotCapabilityError(Exception):
    """A ShotSpec capability binding that the caller must fix (HTTP 422)."""

    def __init__(self, detail: str, *, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def resolve_shot_capability(shot: ShotSpec):
    """Return the capability bound to ``shot``.

    Raises :class:`ShotCapabilityError` (422) when the shot has no binding or
    the bound name is not registered.
    """
    name = shot.capability_name()
    if not name:
        raise ShotCapabilityError(
            f"shot {shot.shot_id}: no capability bound "
            "(expected shot.capability = {'name': ..., 'params': {...}})"
        )
    try:
        return get(name)
    except CapabilityError as exc:
        raise ShotCapabilityError(f"shot {shot.shot_id}: unknown capability: {exc}") from exc


def assemble_shot(
    shot: ShotSpec,
    out_dir: str | Path,
    *,
    aspect: str = "16:9",
    seed: int = 1234,
    duration: float | None = None,
) -> CapabilityResult:
    """Render the capability bound to ``shot`` into ``out_dir``.

    ``duration`` defaults to the shot's ``duration_sec``.  A missing/unknown
    capability, bad params, or an unsupported aspect is a
    :class:`ShotCapabilityError` (422); a render failure is re-raised as a
    ``CapabilityError`` (500-class).
    """
    cap = resolve_shot_capability(shot)
    params = shot.capability_params()
    try:
        cap.validate_params(params)
    except CapabilityError as exc:
        raise ShotCapabilityError(f"shot {shot.shot_id}: invalid capability params: {exc}") from exc
    if not cap.supports_aspect(aspect):
        raise ShotCapabilityError(
            f"shot {shot.shot_id}: capability {cap.name} does not support aspect "
            f"{aspect!r} (supported: {cap.aspects})"
        )
    return cap.render(
        params,
        out_dir,
        duration=float(duration if duration is not None else shot.duration_sec),
        aspect=aspect,
        seed=seed,
    )
