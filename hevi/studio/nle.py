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
    speed: float = 1.0
    reverse: bool = False
    transition: str = "cut"
    effect: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "in_s": self.in_s,
            "duration_s": self.duration_s,
            "speed": self.speed,
            "reverse": self.reverse,
            "transition": self.transition,
            "effect": self.effect,
        }


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
        segments.append(
            RecutSegment(
                source=source,
                in_s=in_s,
                duration_s=duration,
                speed=max(0.25, min(4.0, float(clip.get("speed") or 1.0))),
                reverse=bool(clip.get("reverse")),
                transition=str(clip.get("transition") or "cut"),
                effect=str(clip.get("effect") or "none"),
            )
        )
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


def _effect_filter(effect: str) -> str:
    return {
        "warm": "colorbalance=rs=.08:gs=.03:bs=-.04",
        "cool": "colorbalance=rs=-.04:gs=.02:bs=.08",
        "mono": "hue=s=0",
        "vignette": "vignette=PI/4",
        "sharpen": "unsharp=5:5:0.8:5:5:0",
    }.get(effect, "")


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
                # duration_s is the desired timeline/output duration.  Read
                # enough source media before setpts/atempo changes its speed.
                f"{seg.duration_s * seg.speed:.3f}",
                "-i",
                seg.source,
            ]
        )
    if plan.bgm and Path(plan.bgm).exists():
        args.extend(["-i", plan.bgm])
    has_transform = any(
        seg.speed != 1.0 or seg.reverse or seg.effect != "none" for seg in plan.segments
    )
    filter_complex = plan.filter_complex
    if has_transform:
        transformed: list[str] = []
        for i, segment in enumerate(plan.segments):
            video = f"[{i}:v]setpts=PTS/{segment.speed:.4f}"
            audio = f"[{i}:a]"
            if segment.reverse:
                video += ",reverse"
                audio += "areverse"
            effect = _effect_filter(segment.effect)
            if effect:
                video += f",{effect}"
            video += f"[v{i}]"
            tempo = segment.speed
            tempo_parts: list[str] = []
            while tempo < 0.5:
                tempo_parts.append("atempo=0.5")
                tempo /= 0.5
            while tempo > 2.0:
                tempo_parts.append("atempo=2.0")
                tempo /= 2.0
            tempo_parts.append(f"atempo={tempo:.4f}")
            audio += "," + ",".join(tempo_parts) + f"[a{i}]"
            transformed.extend((video, audio))
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(plan.segments)))
        filter_complex = ";".join(
            [*transformed, f"{joined}concat=n={len(plan.segments)}:v=1:a=1[v][a]"]
        )
        if plan.bgm and Path(plan.bgm).exists():
            n = len(plan.segments)
            filter_complex += f";[{n}:a]volume=0.28[b];[a][b]amix=inputs=2:duration=first:dropout_transition=2[mix]"
    if filter_complex:
        args.extend(["-filter_complex", filter_complex])
        mapped = "[mix]" if plan.bgm and Path(plan.bgm).exists() else "[a]"
        args.extend(["-map", "[v]", "-map", mapped])
    args.extend(["-c:v", "libx264", "-c:a", "aac", "-shortest", plan.output])
    return args
