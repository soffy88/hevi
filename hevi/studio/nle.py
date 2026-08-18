"""成片时间线:导入 → 切/丢/换 BGM → ffmpeg 重导出,不重跑产线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RecutSegment:
    source: str
    in_s: float
    duration_s: float

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "in_s": self.in_s, "duration_s": self.duration_s}


@dataclass
class RecutPlan:
    segments: list[RecutSegment] = field(default_factory=list)
    bgm: str = ""
    output: str = ""
    filter_complex: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [item.to_dict() for item in self.segments],
            "bgm": self.bgm,
            "output": self.output,
            "filter_complex": self.filter_complex,
        }


def plan_recut(
    clips: list[dict[str, Any]],
    *,
    bgm: str = "",
    output: str = "output/nle/recut.mp4",
    film: str = "",
) -> RecutPlan:
    segments: list[RecutSegment] = []
    for clip in clips:
        if str(clip.get("action") or "keep") == "drop":
            continue
        if str(clip.get("track") or "video") != "video":
            continue
        source = str(clip.get("source") or film or "")
        if not source:
            continue
        duration = max(0.04, float(clip.get("duration_s") or 0.0))
        in_s = float(clip.get("source_in_s") or 0.0)
        segments.append(RecutSegment(source=source, in_s=in_s, duration_s=duration))
    has_bgm = bool(bgm) and Path(bgm).exists()
    filt = _concat_filter(len(segments), has_bgm=has_bgm)
    return RecutPlan(
        segments=segments,
        bgm=bgm if has_bgm else "",
        output=output,
        filter_complex=filt,
    )


def _concat_filter(n: int, *, has_bgm: bool) -> str:
    if n <= 0:
        return ""
    joined = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    body = f"{joined}concat=n={n}:v=1:a=1[v][a]"
    if not has_bgm:
        return body
    mix = f"[{n}:a]volume=0.28[b];[a][b]amix=inputs=2:duration=first:dropout_transition=2[mix]"
    return f"{body};{mix}"


def ffmpeg_recut_args(plan: RecutPlan) -> list[str]:
    if not plan.segments:
        return []
    args: list[str] = ["-y"]
    for seg in plan.segments:
        args.extend(
            [
                "-ss",
                f"{seg.in_s:.3f}",
                "-t",
                f"{seg.duration_s:.3f}",
                "-i",
                seg.source,
            ]
        )
    if plan.bgm and Path(plan.bgm).exists():
        args.extend(["-i", plan.bgm])
    if plan.filter_complex:
        args.extend(["-filter_complex", plan.filter_complex])
        mapped = "[mix]" if plan.bgm and Path(plan.bgm).exists() else "[a]"
        args.extend(["-map", "[v]", "-map", mapped])
    args.extend(["-c:v", "libx264", "-c:a", "aac", "-shortest", plan.output])
    return args
