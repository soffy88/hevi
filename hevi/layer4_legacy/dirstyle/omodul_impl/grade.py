"""CPU-style grade workflow (omodul, ffmpeg-based).

Input: a video file (or keyframe sequence) + a style id.
Output: a 9:16 styled video segment with the style's grade applied.
"""
from __future__ import annotations

import hashlib
import json
import re
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


def _parse_signalstats(text: str) -> dict[str, float]:
    """Parse lavfi.signalstats key=value pairs into means.

    Keys of interest: YAVG/UAVG/VAVG/SATAVG.  Every frame emits a
    block of `lavfi.signalstats.<KEY>=<value>` lines; the mean over
    all frames is returned per key (0.0 when absent).
    """
    keys = ("YAVG", "UAVG", "VAVG", "SATAVG")
    pattern = re.compile(r"lavfi\.signalstats\.(YAVG|UAVG|VAVG|SATAVG)=(-?[\d.]+)")
    vals: dict[str, list[float]] = {k: [] for k in keys}
    for m in pattern.finditer(text):
        try:
            vals[m.group(1)].append(float(m.group(2)))
        except ValueError:
            pass
    return {
        f"{k.lower()}_mean": (sum(v) / len(v) if v else 0.0)
        for k, v in vals.items()
    }


def signalstats_mean(video: Path) -> dict[str, float]:
    """Read Y/U/V/SAT means from a video via ffmpeg signalstats metadata."""
    out = subprocess.run(
        ["ffmpeg", "-i", str(video),
         "-vf", "signalstats,metadata=print",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    return _parse_signalstats(out.stderr)


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


# ---------------------------------------------------------------------------
# 9:16 reframing (B2 fix)
# ---------------------------------------------------------------------------

def _hex_to_ffmpeg_color(hex_color: str) -> str:
    """Convert #RRGGBB to ffmpeg color string 0xRRGGBB."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return f"0x{h}"


def _parse_zoom(zoom_str: str) -> float:
    """Parse zoompan z expression baseline (e.g. '1.00+0.06*on/349')."""
    try:
        # Extract leading float
        import re as _re
        m = _re.match(r"([\d.]+)", zoom_str)
        return float(m.group(1)) if m else 1.0
    except Exception:
        return 1.0


def build_reframe_complex(
    style_id: str,
    reframe: dict[str, Any],
    input_label: str = "[0:v]",
    fps: float = 30.0,
    duration_s: float = 0.0,
) -> tuple[str, str]:
    """Build a filter_complex string implementing a per-style 9:16 reframe.

    Layout: background layer (color field / blurred cover) + foreground
    layer (full 16:9 frame scaled to fg_width) overlaid at (fg_x, fg_y).
    The foreground is never cropped horizontally; the subject is preserved.

    Returns (filter_complex, description).
    """
    target_w, target_h = 1080, 1920
    fg_w = int(reframe.get("fg_width", target_w))
    fg_y = int(reframe.get("fg_y", 0))
    fg_x = int(reframe.get("fg_x", (target_w - fg_w) // 2))
    bg_mode = reframe.get("bg_mode", "solid_color")
    bg_color = reframe.get("bg_color", "#000000")
    motion = reframe.get("motion", "static_centered")
    zoom_start = float(reframe.get("zoom_start", 1.0))
    zoom_end = float(reframe.get("zoom_end", zoom_start))
    bg_blur = int(reframe.get("bg_blur", 40))
    bg_bands = reframe.get("bg_bands", [])
    band_h = int(reframe.get("band_h", 240))
    vignette = float(reframe.get("vignette", 0.0))

    # ---- Foreground: full 16:9 frame scaled to fg_width, kept intact ----
    # fg_h computed from 16:9 aspect: h = w * 9 / 16
    fg_h = int(fg_w * 9 / 16)
    # Clamp so foreground fits vertically
    if fg_y + fg_h > target_h:
        fg_y = max(0, target_h - fg_h)

    fg_chain = f"{input_label}scale={fg_w}:{fg_h}:flags=lanczos[fg]"

    # ---- Background ----
    bg_chains: list[str] = []
    bg_chains.append(fg_chain)  # fg chain first (so [fg] label exists)
    if bg_mode in ("solid_color", "pastel_color_field", "saturated_color_field"):
        bg_chains.append(
            f"color=c={_hex_to_ffmpeg_color(bg_color)}:s={target_w}x{target_h}:r={fps}[bgbase]"
        )
        if bg_bands and len(bg_bands) >= 2 and bg_mode == "pastel_color_field":
            # Symmetric top/bottom color bands via drawbox
            c1 = _hex_to_ffmpeg_color(bg_bands[0])
            c2 = _hex_to_ffmpeg_color(bg_bands[1])
            bg_chains.append(
                f"[bgbase]drawbox=x=0:y=0:w={target_w}:h={band_h}:color={c1}@1:t=fill,"
                f"drawbox=x=0:y={target_h - band_h}:w={target_w}:h={band_h}:color={c2}@1:t=fill[bg]"
            )
        else:
            bg_chains.append("[bgbase]null[bg]")
    elif bg_mode in ("blurred_dark", "blurred_color_bands"):
        # Blurred cover of the source itself, darkened
        bg_chains.append(
            f"{input_label}scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},boxblur={bg_blur}:2,eq=brightness=-0.25:saturation=1.1[bgbase]"
        )
        if bg_bands and len(bg_bands) >= 2 and bg_mode == "blurred_color_bands":
            c1 = _hex_to_ffmpeg_color(bg_bands[0])
            c2 = _hex_to_ffmpeg_color(bg_bands[1])
            bg_chains.append(
                f"[bgbase]drawbox=x=0:y=0:w={target_w}:h={band_h}:color={c1}@0.55:t=fill,"
                f"drawbox=x=0:y={target_h - band_h}:w={target_w}:h={band_h}:color={c2}@0.55:t=fill[bg]"
            )
        else:
            bg_chains.append("[bgbase]null[bg]")
    else:
        bg_chains.append(
            f"color=c={_hex_to_ffmpeg_color(bg_color)}:s={target_w}x{target_h}:r={fps}[bg]"
        )

    # ---- Vignette (optional) ----
    if vignette > 0:
        bg_chains.append(f"[bg]vignette=PI/{max(1.0, 1.0 / vignette):.4f}[bgv]")
        bg_label = "[bgv]"
    else:
        bg_label = "[bg]"

    # ---- Motion: slow push-in via zoompan on the foreground ----
    fg_label = "[fg]"
    if motion == "slow_push_in" and zoom_end > zoom_start and duration_s > 0:
        # Use zoompan with d=1 (one output frame per input frame)
        # so duration is preserved. z expression ramps from zoom_start
        # to zoom_end over the clip.
        total_frames = max(2, int(round(duration_s * fps)))
        z_expr = f"{zoom_start:.4f}+{zoom_end - zoom_start:.4f}*on/{total_frames}"
        # zoompan zooms into the center of the fg stream
        fg_chains = (
            f"[fg]zoompan=z='{z_expr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={fg_w}x{fg_h}:fps={fps}[fgz]"
        )
        fg_label = "[fgz]"
        bg_chains.append(fg_chains)
    elif motion == "slight_drift" and duration_s > 0:
        # Gentle horizontal drift via crop with time expression
        max_drift = 40
        crop_x = f"(iw-{fg_w})/2+{max_drift}*sin(2*PI*t/{max(1.0, duration_s)})"
        fg_chains = (
            f"[fg]scale={fg_w + max_drift * 2}:{fg_h}:flags=lanczos,"
            f"crop={fg_w}:{fg_h}:x='{crop_x}':y=0[fgd]"
        )
        fg_label = "[fgd]"
        bg_chains.append(fg_chains)

    # ---- Overlay ----
    overlay = f"{bg_label}{fg_label}overlay=x={fg_x}:y={fg_y}:shortest=1[out]"
    complex_str = ";".join(bg_chains) + ";" + overlay
    desc = (
        f"reframe_9x16: bg_mode={bg_mode}, fg={fg_w}x{fg_h} at ({fg_x},{fg_y}), "
        f"motion={motion}, bg_bands={len(bg_bands)}, vignette={vignette}"
    )
    return complex_str, desc


def run_style_grade(
    input_video: str | Path,
    style_grade: dict[str, Any],
    output_path: str | Path,
    target_w: int = 1080,
    target_h: int = 1920,
    *,
    aspect_mode: str = "letterbox",
    reframe: dict[str, Any] | None = None,
    style_id: str = "",
) -> GradeResult:
    """Run ffmpeg grade pass on input_video → output_path.

    For wide-aspect styles in 9:16 canvas, adds letterbox padding.
    When *reframe* (a style's ``reframe_9x16`` block) is given, the
    per-style 9:16 recomposition is built from it instead: a background
    layer (color field / blurred cover) plus the full 16:9 foreground
    scaled to fg_width and overlaid at (fg_x, fg_y) — no hard crop.
    """
    inp = Path(input_video)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    input_sha = sha256_file(inp)
    steps, filter_str = build_filter_chain(style_grade)

    # Per-style 9:16 recomposition (B2): build a filter_complex
    # from the style's reframe_9x16 parameters.
    if reframe and isinstance(reframe, dict):
        # First apply the grade steps to the input, then reframe.
        # The grade is applied on a pre-labeled stream.
        pre_label = "[graded]"
        grade_part = filter_str + (f",{pre_label}" if False else "")
        # Build the complex: grade on input -> [graded], then reframe
        reframe_complex, desc = build_reframe_complex(
            style_id=style_id,
            reframe=reframe,
            input_label=pre_label,
            fps=30.0,
            duration_s=0.0,
        )
        # Prepend the grade chain to the reframe complex
        full_complex = f"{input_label if False else '[0:v]'}{filter_str}{pre_label};{reframe_complex}" if False else None
        # Simpler: run grade first as -vf, then reframe as -filter_complex
        # We do it in two passes for correctness with ffmpeg
        # Pass 1: grade -> intermediate
        inter = out.parent / f".{out.stem}_graded.mp4"
        cmd_grade = [
            "ffmpeg", "-y",
            "-i", str(inp),
            "-vf", filter_str,
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "copy",
            str(inter),
        ]
        proc = subprocess.run(cmd_grade, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            inter.unlink(missing_ok=True)
            raise RuntimeError(
                f"ffmpeg grade pass failed for {inp}:\n"
                f"cmd: {' '.join(cmd_grade)}\nstderr: {proc.stderr[-2000:]}"
            )
        # Probe intermediate for duration/fps
        inter_info = probe_video(inter)
        dur = inter_info["duration"]
        fps_val = 30.0
        try:
            num, den = inter_info["fps"].split("/")
            fps_val = float(num) / max(1.0, float(den))
        except Exception:
            pass
        reframe_complex, desc = build_reframe_complex(
            style_id=style_id,
            reframe=reframe,
            input_label="[0:v]",
            fps=fps_val,
            duration_s=dur,
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(inter),
            "-filter_complex", reframe_complex,
            "-map", "[out]",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "copy",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        inter.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg reframe failed for {inp} -> {out}:\n"
                f"cmd: {' '.join(cmd)}\nstderr: {proc.stderr[-2000:]}"
            )
        filter_parts = [f"GRADE:{filter_str}", f"REFRAME:{desc}"]
    else:
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
        style_id=style_id,
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
    "build_reframe_complex",
    "probe_video",
    "run_style_grade",
    "sha256_file",
    "signalstats_mean",
]
