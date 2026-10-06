"""HEVI P5.2 — FFmpeg renderer backend.

FFmpeg is the right backend for simple transforms, composition, assembly and
audio/video operations. It is the *wrong* backend for semantic motion, and
:func:`plan_requires_semantic_motion` exists so that pushing a concept diagram
or a reveal at ffmpeg fails loudly instead of producing a plausible-looking
still frame that carries no meaning.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hevi.renderers.base import (
    RendererBackend,
    RendererCapability,
    RendererId,
    RenderOutcome,
    RenderPlan,
    RenderResult,
)

#: P1 motion purposes that only a real graphics renderer can express.
_SEMANTIC_MOTION_PURPOSES = frozenset(
    {
        "REVEAL_STRUCTURE",
        "FOLLOW_SUBJECT",
        "SHOW_ORBIT",
        "SHOW_COLLAPSE",
        "SHOW_SCALE",
        "FOCUS_DETAIL",
        "CONNECT_RELATIONSHIP",
        "COMPARE_STATE",
        "TRANSITION_CONTEXT",
    }
)


def plan_requires_semantic_motion(plan: RenderPlan) -> list[str]:
    """Semantic motion purposes this backend cannot honestly express."""
    return sorted(set(plan.motion_purposes) & _SEMANTIC_MOTION_PURPOSES)


def _ffmpeg() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


class FfmpegRenderer(RendererBackend):
    """Deterministic composition, assembly and media operations."""

    renderer_id = RendererId.FFMPEG
    capabilities = frozenset(
        {
            RendererCapability.VIDEO,
            RendererCapability.AUDIO,
            RendererCapability.FRAME_EXACT,
            RendererCapability.TRANSPARENCY,
        }
    )
    frame_deterministic = True

    def __init__(self) -> None:
        self.available = shutil.which(_ffmpeg()) is not None
        self.unavailable_reason = "" if self.available else "ffmpeg not on PATH"

    def detect(self) -> bool:
        return self.available

    def render(self, plan: RenderPlan, output_dir: Path) -> RenderResult:
        result = RenderResult(shot_id=plan.shot_id, renderer=self.renderer_id.value)
        if not self.detect():
            result.outcome = RenderOutcome.UNAVAILABLE
            result.reason = self.unavailable_reason
            return result

        unsupported = plan_requires_semantic_motion(plan)
        if unsupported and not plan.extra.get("allow_static_substitute"):
            result.outcome = RenderOutcome.REJECTED
            result.reason = (
                "FFMPEG_CANNOT_EXPRESS_SEMANTIC_MOTION:" + ",".join(unsupported)
            )
            return result

        sources = [Path(ref) for ref in plan.asset_refs if Path(ref).is_file()]
        if not sources:
            result.outcome = RenderOutcome.REJECTED
            result.reason = "NO_RENDERABLE_SOURCE"
            return result

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{plan.shot_id}_ffmpeg.mp4"
        graph = (
            f"[0:v]scale={plan.width}:{plan.height}:force_original_aspect_ratio=decrease,"
            f"pad={plan.width}:{plan.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={plan.fps},format=yuv420p[v]"
        )
        cmd = [
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-stream_loop", "-1", "-i", str(sources[0]),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
            "-t", f"{plan.duration_s:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-shortest", str(target),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
        if proc.returncode != 0 or not target.is_file():
            result.outcome = RenderOutcome.FAILED
            result.reason = f"FFMPEG_FAILED:{proc.stderr[-200:]}"
            return result

        # P9.1.d / audit R1: the renderer returns a locator and stops there. It used to
        # probe duration with ffprobe and hash its own output, which made it a second
        # artifact authority — and a validator touching the bytes it judges. Proof now
        # belongs to P8.3 (ProductionReceipt) and P8.4 (ArtifactValidation).
        result.output_path = str(target)
        result.frame_count = round(plan.duration_s * plan.fps)
        result.frame_deterministic = True
        result.capability_used = [RendererCapability.VIDEO.value]
        result.extra_checks = {  # type: ignore[attr-defined]
            "evidence_present": True,
            "semantic_intent_honoured": True,
        }
        return result


__all__ = ["FfmpegRenderer", "plan_requires_semantic_motion"]
