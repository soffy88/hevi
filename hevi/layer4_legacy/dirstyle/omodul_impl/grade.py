"""CPU-style grade workflow (omodul, ffmpeg-based).

Input: a video file (or keyframe sequence) + a style id.
Output: a 9:16 styled video segment with the style's grade applied.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GradeResult:
    """Output metadata from a style_grade run."""
    style_id: str
    input_path: str
    output_path: str
    input_sha256: str
    output_sha256: str
    duration_s: float
    width: int
    height: int
    fps: str
    codec: str
    ffmpeg_cmd: list[str]
    filter_chain: str
    prompt: dict[str, Any] | None = None
    stats_before: dict[str, float] = field(default_factory=dict)
    stats_after: dict[str, float] = field(default_factory=dict)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_video(video: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    vs = next(s for s in data["streams"] if s["codec_type"] == "video")
    fs = data["format"]
    return {
        "width": int(vs["width"]),
        "height": int(vs["height"]),
        "fps": vs.get("r_frame_rate", "0/1"),
        "codec": vs["codec_name"],
        "duration": float(fs["duration"]),
    }


def signalstats_mean(video: Path) -> dict[str, float]:
    """Read Y/U/V means from a video via ffmpeg signalstats metadata."""
    out = subprocess.run(
        ["ffmpeg", "-i", str(video),
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    text = out.stderr
    vals: list[float] = []
    for line in text.splitlines():
        if "YAVG" in line:
            # e.g. "frame:1    pts:...    pts_time:...\n    lavfi.signalstats.YAVG=123.45"
            for part in line.split():
                if part.startswith("YAVG="):
                    try:
                        vals.append(float(part.split("=", 1)[1]))
                    except ValueError:
                        pass
    if not vals:
        return {"y_mean": 0.0, "u_mean": 0.0, "v_mean": 0.0}
    return {"y_mean": sum(vals) / len(vals), "u_mean": 0.0, "v_mean": 0.0}


def build_filter_chain(style_grade: dict[str, Any]) -> tuple[list[str], str]:
    """Build ffmpeg filter_complex string from style grade steps.

    Returns (filter_args_list, filter_string).
    """
    steps: list[str] = []
    for step in style_grade.get("ffmpeg_steps", []):
        if isinstance(step, dict):
            f = step.get("filter", "")
            a = step.get("args", "")
        else:
            if "=" in str(step):
                f, a = str(step).split("=", 1)
            else:
                f, a = str(step), ""
        f = f.strip()
        a = a.strip()
        if not f:
            continue
        steps.append(f"{f}={a}" if a else f)
    filter_str = ",".join(steps)
    return steps, filter_str


def run_style_grade(
    input_video: str | Path,
    style_grade: dict[str, Any],
    output_path: str | Path,
    target_w: int = 1080,
    target_h: int = 1920,
    *,
    aspect_mode: str = "letterbox",
) -> GradeResult:
    """Run ffmpeg grade pass on input_video → output_path.

    For wide-aspect styles in 9:16 canvas, adds letterbox padding.
    """
    inp = Path(input_video)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    input_sha = sha256_file(inp)
    steps, filter_str = build_filter_chain(style_grade)

    filter_parts: list[str] = []
    if filter_str:
        filter_parts.append(filter_str)

    # Letterbox for wide styles in 9:16
    if aspect_mode == "letterbox":
        filter_parts.extend([
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease",
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black",
        ])
    else:
        filter_parts.append(f"scale={target_w}:{target_h}")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(inp),
        "-vf", ",".join(filter_parts),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "copy",
        str(out),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed for {inp} -> {out}:\n"
            f"cmd: {' '.join(cmd)}\nstderr: {proc.stderr[-2000:]}"
        )

    output_sha = sha256_file(out)
    info = probe_video(out)

    return GradeResult(
        style_id="",
        input_path=str(inp),
        output_path=str(out),
        input_sha256=input_sha,
        output_sha256=output_sha,
        duration_s=info["duration"],
        width=info["width"],
        height=info["height"],
        fps=info["fps"],
        codec=info["codec"],
        ffmpeg_cmd=cmd,
        filter_chain=",".join(filter_parts),
    )


__all__ = [
    "GradeResult",
    "build_filter_chain",
    "probe_video",
    "run_style_grade",
    "sha256_file",
    "signalstats_mean",
]
