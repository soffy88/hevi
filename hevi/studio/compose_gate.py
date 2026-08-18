"""数字人 = 基础片过检后再叠,不是烤进 L6。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def qc_allows_compose(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    if report.get("ok") is True or report.get("passed") is True:
        return True
    return str(report.get("status") or "").lower() in {"ok", "passed", "completed"}


def compose_after_qc_enabled(flag: bool | None = None) -> bool:
    if flag is False:
        return False
    env = os.environ.get("HEVI_COMPOSE_AFTER_QC", "").strip().lower()
    return bool(flag) or env in {"1", "true", "yes"}


def should_defer_avatar(
    *,
    preview: bool = False,
    compose_after_qc: bool | None = None,
    has_presenter: bool = False,
) -> bool:
    if preview or not has_presenter:
        return False
    return compose_after_qc_enabled(compose_after_qc)


async def apply_compose_after_qc(
    *,
    base_video: str | Path,
    image_path: str | Path | None,
    audio_path: str | Path | None,
    output_path: str | Path,
    qc_report: dict[str, Any] | None,
    compose_fn: Any = None,
) -> dict[str, Any]:
    if not qc_allows_compose(qc_report):
        return {"status": "skipped", "reason": "qc failed or missing"}
    if not image_path or not audio_path:
        return {"status": "skipped", "reason": "presenter or audio missing"}
    payload = {
        "image_path": str(image_path),
        "audio_path": str(audio_path),
        "output_path": str(output_path),
        "base_video": str(base_video),
    }
    if compose_fn is None:
        from hevi.studio.kit import avatar_compose

        compose_fn = avatar_compose
    result = await compose_fn(payload)
    if isinstance(result, dict):
        result.setdefault("base_video", str(base_video))
        return result
    return {"status": "ok", "avatar_path": str(result), "base_video": str(base_video)}
