"""OMQUALITY appearance layer — public API for the enhancement capabilities.

A thin facade over :mod:`hevi.layer4_legacy.enhance`.  Same idiom as
``hevi.talkcraft`` (which sits over ``hevi.layer4_legacy.talkcraft``):
consumers import the omodul-backed function from the top-level module; the
internal layering never leaks into the call site.
"""

from __future__ import annotations

from typing import Any

from hevi.layer4_legacy.enhance.omodul_impl.compare import build_comparison_sheet
from hevi.layer4_legacy.enhance.omodul_impl.enhance_workflow import (
    EnhanceConfigError,
    EnhanceUnavailable,
    enhance_media_workflow,
)

__all__ = [
    "EnhanceConfigError",
    "EnhanceUnavailable",
    "build_comparison_sheet",
    "enhance_media",
]


def enhance_media(
    *,
    op: str,
    input_path: str,
    output_dir: str,
    config: dict[str, Any] | None = None,
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for :func:`enhance_media_workflow`.

    Pass ``op`` ("matte" / "upscale" / "face_restore" / "lut") explicitly; the
    rest of ``config`` is forwarded verbatim (scale, look, intensity, ...).
    """
    cfg = dict(config or {})
    cfg.setdefault("op", op)
    data = dict(input_data or {})
    data.setdefault("input_path", input_path)
    return enhance_media_workflow(cfg, data, output_dir)
