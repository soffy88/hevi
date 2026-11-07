"""Word-pop subtitle renderer (``video.word_pop_renderer``).

Clean-room restatement of the tutorial method in
``hevi-vs-3d-cartoon-tutorial-6steps.md`` section 2 item 6: subtitles
appear one word at a time in large type at the bottom of the frame,
never covering a face. This module renders that behaviour locally
from a contract already judged by ``qa.word_pop_subtitle_contract``:

1. The contract is re-judged here first; a failing contract never
   renders.
2. The subtitle zone is checked against every declared face box
   before a single frame is drawn. Any overlap fails closed with
   ``CapabilityError`` -- the renderer never draws text over a
   face and calls it a pass.
3. Frames are drawn with Pillow (one word popping in per word
   window, scale growing over the declared pop window) and
   assembled with ffmpeg. Sampled frames are pixel-checked
   in-process: the subtitle zone must change while a word is
   shown and stay at the background colour before the first word.

This is a local synthesis renderer for the pop behaviour. It is
not a claim about any external engine, and CJK text needs a CJK
font in place (recorded in the evidence when the fallback font
is used).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.word_pop_subtitle_contract import (
    check_word_pop_subtitle_contract,
)

_Registered = False

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _resolve_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, str]:
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size), str(path)
    return ImageFont.load_default(), "builtin-default (no CJK support)"


def _rects_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax, ay, aw, ah = (float(a[k]) for k in ("x", "y", "w", "h"))
    bx, by, bw, bh = (float(b[k]) for k in ("x", "y", "w", "h"))
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def render_word_pop(
    plan: dict[str, Any],
    output_path: str | Path,
    *,
    fps: int = 30,
    width: int = 540,
    height: int = 960,
) -> dict[str, Any]:
    """Render a word-pop subtitle pass. Returns the evidence record.

    Raises ``CapabilityError`` on a failing contract, a face
    overlap, a missing ffmpeg, or a failed pixel check. Never
    returns a fabricated success.
    """
    contract_report = check_word_pop_subtitle_contract(plan)
    if not contract_report["ok"]:
        raise CapabilityError(
            "video.word_pop_renderer: contract failed: "
            + "; ".join(
                f"{issue['code']}: {issue['detail']}"
                for issue in contract_report["issues"]
            )
        )
    if shutil.which("ffmpeg") is None:
        raise CapabilityError("video.word_pop_renderer: ffmpeg not found; environment_missing")
    zone = plan["subtitle_zone"]
    faces = plan.get("face_boxes", [])
    for face in faces:
        if isinstance(face, dict) and _rects_overlap(zone, face):
            raise CapabilityError(
                "video.word_pop_renderer: subtitle zone overlaps a face box; refused to render"
            )
    words = contract_report["words"]
    pop = plan["pop"]
    scale_from = float(pop["scale_from"])
    scale_to = float(pop["scale_to"])
    window_s = float(pop["window_s"])
    total_s = max(float(word["end_s"]) for word in words)
    total_frames = max(1, int(round(total_s * fps)))
    zone_px = {
        "x": int(float(zone["x"]) * width),
        "y": int(float(zone["y"]) * height),
        "w": int(float(zone["w"]) * width),
        "h": int(float(zone["h"]) * height),
    }
    bg = (16, 24, 39)
    face_fill = (70, 90, 120)
    text_fill = (255, 255, 255)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    font_path, font_note = _resolve_font(max(12, zone_px["h"] // 2))
    zone_means: dict[int, tuple[float, float, float]] = {}
    words_shown: list[str] = []
    with tempfile.TemporaryDirectory(prefix="word_pop_frames_") as tmp:
        frames_dir = Path(tmp)
        for index in range(total_frames):
            t = index / fps
            active = next(
                (w for w in words if float(w["start_s"]) <= t < float(w["end_s"])),
                None,
            )
            frame = Image.new("RGB", (width, height), bg)
            draw = ImageDraw.Draw(frame)
            for face in faces:
                if isinstance(face, dict):
                    draw.rectangle(
                        [
                            int(float(face["x"]) * width),
                            int(float(face["y"]) * height),
                            int((float(face["x"]) + float(face["w"])) * width),
                            int((float(face["y"]) + float(face["h"])) * height),
                        ],
                        fill=face_fill,
                    )
            draw.rectangle(
                [
                    zone_px["x"],
                    zone_px["y"],
                    zone_px["x"] + zone_px["w"],
                    zone_px["y"] + zone_px["h"],
                ],
                outline=(90, 110, 140),
            )
            if active is not None:
                progress = min(1.0, (t - float(active["start_s"])) / window_s)
                ease = 1.0 - (1.0 - progress) ** 2
                scale = scale_from + (scale_to - scale_from) * ease
                font, _ = _resolve_font(max(12, int(zone_px["h"] * 0.5 * scale)))
                bbox = draw.textbbox((0, 0), str(active["word"]), font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text(
                    (
                        zone_px["x"] + (zone_px["w"] - tw) // 2 - bbox[0],
                        zone_px["y"] + (zone_px["h"] - th) // 2 - bbox[1],
                    ),
                    str(active["word"]),
                    font=font,
                    fill=text_fill,
                )
                if str(active["word"]) not in words_shown:
                    words_shown.append(str(active["word"]))
            zone_crop = frame.crop(
                (
                    zone_px["x"],
                    zone_px["y"],
                    zone_px["x"] + zone_px["w"],
                    zone_px["y"] + zone_px["h"],
                )
            )
            zone_means[index] = tuple(ImageStat.Stat(zone_crop).mean)
            frame.save(frames_dir / f"f_{index:04d}.png")
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-framerate", str(fps),
                "-i", str(frames_dir / "f_%04d.png"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            raise CapabilityError(
                f"video.word_pop_renderer: ffmpeg assembly failed: {result.stderr.strip()}"
            )
    first_word_start = min(float(w["start_s"]) for w in words)
    pre_frames = [i for i in range(total_frames) if i / fps < first_word_start]
    if pre_frames:
        pre_mean = zone_means[pre_frames[0]]
        if any(abs(value - bg[i]) > 8 for i, value in enumerate(pre_mean)):
            raise CapabilityError(
                "video.word_pop_renderer: subtitle zone is not clean before the first word"
            )
    mid_checks = 0
    for word in words:
        mid = int(((float(word["start_s"]) + float(word["end_s"])) / 2) * fps)
        if mid < total_frames:
            mean = zone_means[mid]
            if all(abs(value - bg[i]) <= 8 for i, value in enumerate(mean)):
                raise CapabilityError(
                    f"video.word_pop_renderer: word '{word['word']}' not visible at its midpoint"
                )
            mid_checks += 1
    if mid_checks == 0:
        raise CapabilityError("video.word_pop_renderer: no word midpoint could be checked")
    evidence: dict[str, Any] = {
        "ok": True,
        "mp4": str(output),
        "sha256": compute_sha256(output),
        "frames": total_frames,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_s": total_frames / fps,
        "words_rendered": words_shown,
        "words_declared": [str(w["word"]) for w in words],
        "face_overlap": False,
        "font": font_note,
        "timestamp_source": plan.get("timestamp_source"),
    }
    return evidence


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence = render_word_pop(
        params["plan"],
        out_dir / "word_pop.mp4",
        fps=int(params.get("fps", 30)),
        width=int(params.get("width", 540)),
        height=int(params.get("height", 960)),
    )
    (out_dir / "word_pop_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=float(evidence["duration_s"]),
        sha256=evidence["sha256"],
        qa={
            "evidence_json": str(out_dir / "word_pop_evidence.json"),
            "ok": True,
        },
    )


def register_word_pop_renderer_capabilities_once() -> list[str]:
    """Register ``video.word_pop_renderer`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.word_pop_renderer",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "fps": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=True,
            description=(
                "Word-pop subtitle renderer: a judged contract is rendered "
                "locally with Pillow and ffmpeg, one word popping in per "
                "window, refusing to draw over a declared face. Pixel "
                "checks verify visibility; failures raise."
            ),
            line="video",
        )
    )
    return ["video.word_pop_renderer"]


register_word_pop_renderer_capabilities_once()
