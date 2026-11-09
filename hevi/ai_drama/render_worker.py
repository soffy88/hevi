"""Dedicated drama render worker contract.

The API image stays the general-purpose image.  Heavy offline drama rendering
(SD-Turbo keyframes, Wav2Lip, ffmpeg assembly) is claimed only by a worker whose
``resource_class`` is ``drama_render``.  The generic ``hevi-worker`` explicitly
excludes that class (see ``hevi.tasks.repository.exclusive_resource_classes``).
"""

from __future__ import annotations

import os
from typing import Any

DRAMA_RENDER_CLASS = "drama_render"
DRAMA_LINES = ("ai_drama",)
RESOURCE_CLASS_ENV = "HEVI_WORKER_RESOURCE_CLASS"
RENDER_MODE_ENV = "HEVI_RENDER_MODE"


def drama_line_of(config: dict[str, Any] | None) -> str:
    config = config or {}
    options = config.get("options") if isinstance(config.get("options"), dict) else {}
    return str(
        config.get("line_id")
        or options.get("line_id")
        or (config.get("slots") or {}).get("line_id")
        or ""
    )


def is_drama_render_task(task: dict[str, Any]) -> bool:
    if str(task.get("resource_class") or "") == DRAMA_RENDER_CLASS:
        return True
    return drama_line_of(task.get("config_json") or {}) in DRAMA_LINES


def render_worker_enabled() -> bool:
    return str(os.environ.get(RESOURCE_CLASS_ENV) or "") == DRAMA_RENDER_CLASS


def describe() -> dict[str, Any]:
    return {
        "resource_class": DRAMA_RENDER_CLASS,
        "lines": list(DRAMA_LINES),
        "worker_resource_class": os.environ.get(RESOURCE_CLASS_ENV, ""),
        "render_mode": os.environ.get(RENDER_MODE_ENV, ""),
        "note": "generic hevi-worker excludes drama_render; this worker claims only it",
    }
