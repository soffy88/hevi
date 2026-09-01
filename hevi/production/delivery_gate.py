"""成片交付合同 —— 文件在不等于 completed。

路径 0(解说):compose 后 ffprobe + 音轨 + 时长。
路径 1(导演/短剧):残镜 / 抄定妆照 / 运动承诺被 i2v 微动换掉 → 不得标完成。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CANON_COPY_MAX_RATIO = 0.0  # 返工后仍抄定妆照 = 残片
DURATION_TOLERANCE = 0.10
PREVIEW_MIN_SECONDS = 60.0
PREVIEW_MAX_SECONDS = 90.0
PREVIEW_TARGET_SECONDS = 75.0


class ComposeGateError(RuntimeError):
    """解说成片未通过 compose 门。"""


@dataclass(frozen=True)
class VideoProbe:
    path: Path
    duration_s: float
    has_video: bool
    has_audio: bool
    size_bytes: int


@dataclass(frozen=True)
class DeliveryVerdict:
    ok: bool
    status: str  # completed | failed
    reason: str = ""
    failed_shots: int = 0
    total_shots: int = 0
    canon_copy_ratio: float = 0.0
    motion_fallback: int = 0
    details: dict[str, Any] = field(default_factory=dict)


def probe_video(path: str | Path) -> VideoProbe:
    dest = Path(path)
    size = dest.stat().st_size if dest.is_file() else 0
    if size <= 0:
        return VideoProbe(dest, 0.0, False, False, size)
    if not shutil.which("ffprobe"):
        logger.error("ffprobe 不可用, 无法验证媒体产物: %s", dest)
        return VideoProbe(dest, 0.0, False, False, size)

    def _has(stream: str) -> bool:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                stream,
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(dest),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())

    duration = 0.0
    dur = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if dur.returncode == 0:
        try:
            duration = float((dur.stdout or "0").strip() or 0)
        except ValueError:
            duration = 0.0
    return VideoProbe(dest, duration, _has("v:0"), _has("a:0"), size)


def assert_explainer_compose(
    path: str | Path,
    *,
    expected_duration_s: float | None = None,
    tolerance: float = DURATION_TOLERANCE,
) -> VideoProbe:
    probe = probe_video(path)
    if probe.size_bytes <= 0:
        raise ComposeGateError(f"成片不存在或空文件: {probe.path}")
    if not probe.has_video:
        raise ComposeGateError(f"成片无视频轨: {probe.path}")
    if not probe.has_audio:
        raise ComposeGateError(f"成片缺少音频轨: {probe.path}")
    if expected_duration_s and expected_duration_s > 0 and probe.duration_s > 0:
        lo = expected_duration_s * (1.0 - tolerance)
        hi = expected_duration_s * (1.0 + tolerance)
        if probe.duration_s < lo or probe.duration_s > hi:
            pct = int(tolerance * 100)
            raise ComposeGateError(
                f"成片时长 {probe.duration_s:.2f}s 不在目标 {expected_duration_s:.2f}s ±{pct}%"
            )
    return probe


def _quality(shot: dict[str, Any]) -> dict[str, Any]:
    raw = shot.get("quality_checks")
    return raw if isinstance(raw, dict) else {}


def _is_canon_copy(shot: dict[str, Any]) -> bool:
    checks = _quality(shot)
    if checks.get("keyframe_degraded"):
        return True
    reason = str(shot.get("diagnosis_category") or shot.get("degrade_reason") or "")
    return shot.get("degraded") is True and ("定妆" in reason or "canon" in reason.lower())


def _is_motion_fallback(shot: dict[str, Any]) -> bool:
    checks = _quality(shot)
    if not checks.get("has_action_beats"):
        return False
    return not bool(checks.get("kf2v_action_arc"))


def evaluate_director_delivery(
    shots: list[dict[str, Any]] | None,
    *,
    delivery_promise: str = "motion",
    canon_copy_max_ratio: float = CANON_COPY_MAX_RATIO,
) -> DeliveryVerdict:
    """导演/短剧成片合同。promise=any 只拦「无镜头」;motion 再拦残镜/抄图/微动降级。"""
    rows = list(shots or [])
    if not rows:
        return DeliveryVerdict(
            ok=False,
            status="failed",
            reason="成片无镜头",
            details={"delivery_promise": delivery_promise},
        )
    n_failed = sum(1 for s in rows if not s.get("passed", False))
    n_canon = sum(1 for s in rows if _is_canon_copy(s))
    n_motion = sum(1 for s in rows if _is_motion_fallback(s))
    ratio = n_canon / len(rows)
    blockers: list[str] = []
    if delivery_promise != "any":
        if n_failed:
            blockers.append(f"{n_failed}/{len(rows)} 镜未过裁决")
        if ratio > canon_copy_max_ratio:
            blockers.append(f"抄定妆照 {n_canon}/{len(rows)}")
        if delivery_promise == "motion" and n_motion:
            blockers.append(f"{n_motion} 镜动作降级为 i2v 微动")
    if blockers:
        return DeliveryVerdict(
            ok=False,
            status="failed",
            reason="残片不得标完成: " + "; ".join(blockers),
            failed_shots=n_failed,
            total_shots=len(rows),
            canon_copy_ratio=ratio,
            motion_fallback=n_motion,
            details={"delivery_promise": delivery_promise, "blockers": blockers},
        )
    return DeliveryVerdict(
        ok=True,
        status="completed",
        failed_shots=n_failed,
        total_shots=len(rows),
        canon_copy_ratio=ratio,
        motion_fallback=n_motion,
        details={"delivery_promise": delivery_promise},
    )


def evaluate_preview_delivery(
    probe: VideoProbe,
    *,
    cue_budget_s: float,
    cover_path: Path | None = None,
) -> dict[str, Any]:
    """60–90s 试播检查。片源短于 60s 不判失败,只标记 short_source。"""
    blockers: list[str] = []
    if probe.size_bytes <= 0:
        blockers.append("试播文件为空")
    if not probe.has_video:
        blockers.append("试播无视频轨")
    if not probe.has_audio:
        blockers.append("试播无音频轨")
    cover_ok = bool(cover_path and cover_path.is_file() and cover_path.stat().st_size > 0)
    return {
        "ok": not blockers,
        "status": "passed" if not blockers else "failed",
        "blockers": blockers,
        "duration_s": probe.duration_s,
        "cue_budget_s": cue_budget_s,
        "short_source": cue_budget_s < PREVIEW_MIN_SECONDS,
        "over_budget": cue_budget_s > PREVIEW_MAX_SECONDS,
        "has_cover": cover_ok,
        "path": str(probe.path),
        "size_bytes": probe.size_bytes,
    }


def write_preview_report(output_dir: Path, report: dict[str, Any]) -> Path:
    import json

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "qc-report.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest
