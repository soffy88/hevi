"""Confirmed-text overlay pipeline (``video.confirmed_text_overlay``).

Clean-room rewrite of the *method* in ``hevi-vs-rain-before-stops.md``
item B4 (from the ``<雨停之前>`` field notes): generated models
render written text unreliably, so the field practice was to
generate the picture with the paper blank and lay the confirmed
wording on afterwards, in post. The discipline that makes that
safe is version control of the wording: one letter, one wording,
confirmed by the author, and the wording laid on must be the
wording in the script -- not a recollection of it.

This module is that discipline plus a local overlay execution:

1. ``check_confirmed_text`` judges a confirmed-text record: the
   record must be marked confirmed with a named confirmer, carry
   a version number of at least 1, name no superseding version,
   and its text must appear verbatim in the caller-supplied
   script text. A superseded record, an unconfirmed record, or
   text that differs from the script fails; nothing is overlaid
   from a failing record.
2. ``overlay_confirmed_text`` runs only on a passing record. It
   extracts the source clip's frames locally with ffmpeg, draws
   the confirmed text with Pillow onto the frames inside the
   caller-supplied placement window (position, time window,
   size, colour -- all caller-supplied, no defaults for where
   the words go or how big they are), and re-encodes locally.
   A CJK-capable font is resolved from fonts already installed
   on the host; if none is found the run fails instead of
   rendering unreadable glyphs. The output is verified before
   it is returned: it must exist, its duration must match the
   source, and pixels inside the placement box must actually
   have changed. Audio is not preserved: this pipeline is
   video-only, and that is recorded in every report.

No price and no Seedance route is involved; no model is called;
no key is held. The wording itself is always caller-supplied --
this module never writes, paraphrases, or "fixes" the text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_KNOWN_CJK_FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/unifont/unifont_jp.otf",
    "/usr/share/fonts/opentype/unifont/unifont.otf",
)


def _fail(message: str) -> CapabilityError:
    return CapabilityError(f"video.confirmed_text_overlay: {message}")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "detail": detail}
    issue.update(extra)
    return issue


def check_confirmed_text(record: Any, script_text: Any) -> dict[str, Any]:
    """Judge one confirmed-text record against the script text.

    Returns a report with verdict ``pass`` / ``fail``; never raises
    for a bad record (only a non-object script argument raises, as
    a caller error, because there is then nothing to judge against).
    """
    issues: list[dict[str, Any]] = []
    text_id = None
    version = None
    if not isinstance(record, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "text_id": None,
            "version": None,
            "issues": [_issue("record_not_object", "confirmed-text record must be a JSON object")],
        }
    text_id = record.get("text_id")
    if not isinstance(text_id, str) or not text_id.strip():
        issues.append(_issue("text_id_missing", "record must name a non-empty 'text_id'"))
    else:
        text_id = text_id.strip()
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        issues.append(_issue("text_missing", "record must carry a non-empty 'text'"))
        text = None
    else:
        text = text.strip()
    version = record.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        issues.append(
            _issue("version_invalid", "record 'version' must be an integer of at least 1")
        )
        version = None
    if record.get("confirmed") is not True:
        issues.append(
            _issue("not_confirmed", "record must be marked confirmed=true by the author")
        )
    confirmer = record.get("confirmed_by")
    if not isinstance(confirmer, str) or not confirmer.strip():
        issues.append(
            _issue("confirmed_by_missing", "record must name who confirmed the text")
        )
    superseded_by = record.get("superseded_by")
    if superseded_by is not None:
        if not isinstance(superseded_by, str) or not superseded_by.strip():
            issues.append(
                _issue("superseded_by_invalid", "'superseded_by' must be a non-empty string or absent")
            )
        else:
            issues.append(
                _issue(
                    "superseded",
                    f"this wording was superseded by {superseded_by.strip()!r}; "
                    "only the current confirmed version may be overlaid",
                    superseded_by=superseded_by.strip(),
                )
            )
    if not isinstance(script_text, str):
        raise _fail("script_text must be a string to judge the wording against")
    if text is not None and text not in script_text:
        issues.append(
            _issue(
                "text_script_mismatch",
                "the confirmed text does not appear verbatim in the "
                "supplied script text; the overlaid wording must be "
                "the script wording",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "text_id": text_id,
        "version": version,
        "issues": issues,
    }


def _run(command: list[str], *, what: str) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as exc:
        raise _fail(f"{what} timed out") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        raise _fail(f"{what} failed (exit {proc.returncode}): {tail}")
    return proc


def _probe_video(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        raise _fail("ffprobe is required but not on PATH")
    proc = _run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        what="ffprobe",
    )
    try:
        doc = json.loads(proc.stdout)
    except ValueError as exc:
        raise _fail("ffprobe returned unparseable output") from exc
    video_streams = [s for s in doc.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        raise _fail(f"no video stream found in {path}")
    stream = video_streams[0]
    try:
        fps = float(Fraction(stream["r_frame_rate"]))
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise _fail(f"could not read frame rate from {path}") from exc
    if fps <= 0:
        raise _fail(f"frame rate of {path} is not positive")
    duration = None
    try:
        duration = float(doc.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    if duration is None or duration <= 0:
        raise _fail(f"could not read duration from {path}")
    has_audio = any(s.get("codec_type") == "audio" for s in doc.get("streams", []))
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "duration": duration,
        "has_audio": has_audio,
    }


def _resolve_font(font_paths: Any) -> Path:
    searched: list[str] = []
    candidates: list[str] = []
    if font_paths is not None:
        if not isinstance(font_paths, list) or not all(
            isinstance(p, str) for p in font_paths
        ):
            raise _fail("font_paths must be a list of path strings when supplied")
        candidates.extend(font_paths)
    candidates.extend(_KNOWN_CJK_FONTS)
    for candidate in candidates:
        searched.append(candidate)
        if Path(candidate).is_file():
            return Path(candidate)
    if shutil.which("fc-match") is not None:
        proc = subprocess.run(
            ["fc-match", "--format", "%{file}\n", ":lang=zh"],
            capture_output=True, text=True, timeout=30,
        )
        matched = proc.stdout.strip().splitlines()
        if matched and Path(matched[0]).is_file():
            return Path(matched[0])
        searched.append("fc-match :lang=zh (no usable match)")
    raise _fail(
        "no CJK-capable font was found on this host; searched: "
        + ", ".join(searched)
        + ". Overlaying without one would render unreadable glyphs, so the run fails."
    )


def _parse_placement(placement: Any, width: int, height: int, duration: float) -> dict[str, Any]:
    if not isinstance(placement, dict):
        raise _fail("placement must be a JSON object")
    for field in ("x", "y", "start_s", "end_s", "fontsize"):
        value = placement.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise _fail(f"placement '{field}' must be a number supplied by the caller")
    color = placement.get("color")
    if not isinstance(color, str) or not color.strip():
        raise _fail("placement 'color' must be a non-empty colour string supplied by the caller")
    x, y = int(placement["x"]), int(placement["y"])
    start_s, end_s = float(placement["start_s"]), float(placement["end_s"])
    fontsize = int(placement["fontsize"])
    if x < 0 or y < 0 or x >= width or y >= height:
        raise _fail(f"placement origin ({x}, {y}) lies outside the frame ({width}x{height})")
    if fontsize <= 0:
        raise _fail("placement 'fontsize' must be positive")
    if start_s < 0 or end_s <= start_s:
        raise _fail("placement needs 0 <= start_s < end_s")
    if end_s > duration + 0.05:
        raise _fail(
            f"placement end_s {end_s} is past the source duration {duration:.3f}s"
        )
    padding = placement.get("padding_px", 8)
    if not isinstance(padding, int) or isinstance(padding, bool) or padding < 0:
        raise _fail("placement 'padding_px' must be a non-negative integer when supplied")
    return {
        "x": x, "y": y, "start_s": start_s, "end_s": end_s,
        "fontsize": fontsize, "color": color.strip(), "padding_px": padding,
    }


def _wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _draw_text_on_frame(frame_path: Path, text: str, placement: dict[str, Any], font_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(frame_path).convert("RGBA")
    font = ImageFont.truetype(str(font_path), placement["fontsize"])
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    max_width = image.width - placement["x"] - placement["padding_px"]
    lines = _wrap_text(draw, text, font, max(10, max_width))
    line_height = placement["fontsize"] + 4
    box_w = max(draw.textlength(line, font=font) for line in lines) + 2 * placement["padding_px"]
    box_h = len(lines) * line_height + 2 * placement["padding_px"]
    box = [
        placement["x"],
        placement["y"],
        min(image.width - 1, placement["x"] + int(box_w)),
        min(image.height - 1, placement["y"] + int(box_h)),
    ]
    draw.rectangle(box, fill=(0, 0, 0, 128))
    text_draw = ImageDraw.Draw(overlay)
    for index, line in enumerate(lines):
        text_draw.text(
            (placement["x"] + placement["padding_px"],
             placement["y"] + placement["padding_px"] + index * line_height),
            line, font=font, fill=placement["color"],
        )
    merged = Image.alpha_composite(image, overlay).convert("RGB")
    merged.save(frame_path)


def _extract_single_frame(video: Path, at_s: float, out_path: Path) -> None:
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{at_s:.3f}", "-i", str(video),
            "-frames:v", "1", str(out_path),
        ],
        what="ffmpeg frame extraction",
    )


def _placement_pixels_changed(before_frame: Path, after_frame: Path, placement: dict[str, Any]) -> int:
    from PIL import Image

    a = Image.open(before_frame).convert("RGB")
    b = Image.open(after_frame).convert("RGB")
    if a.size != b.size:
        raise _fail("verification frames differ in size; the overlay cannot be verified")
    x0, y0 = placement["x"], placement["y"]
    box = (x0, y0, a.width, a.height)
    crop_a = a.crop(box)
    crop_b = b.crop(box)
    raw_a = crop_a.tobytes()
    raw_b = crop_b.tobytes()
    changed = 0
    for offset in range(0, len(raw_a), 3):
        if (
            abs(raw_a[offset] - raw_b[offset]) > 40
            or abs(raw_a[offset + 1] - raw_b[offset + 1]) > 40
            or abs(raw_a[offset + 2] - raw_b[offset + 2]) > 40
        ):
            changed += 1
    return changed


def overlay_confirmed_text(
    source_video: Any,
    record: Any,
    script_text: Any,
    placement: Any,
    out_path: Any,
    *,
    font_paths: Any = None,
    ffmpeg_exe: str = "ffmpeg",
) -> dict[str, Any]:
    """Overlay confirmed wording onto a clip. Fail-closed throughout.

    Raises :class:`CapabilityError` for a failing confirmed-text
    record, a bad placement, a missing font or ffmpeg, or an output
    that fails verification. On success returns the report; the
    output video is written to ``out_path``.
    """
    if shutil.which(ffmpeg_exe) is None:
        raise _fail(f"{ffmpeg_exe} is required but not on PATH")
    if not isinstance(source_video, (str, Path)) or not str(source_video).strip():
        raise _fail("source_video must be a non-empty path string")
    source = Path(str(source_video))
    if not source.is_file():
        raise _fail(f"source video not found: {source}")
    if not isinstance(out_path, (str, Path)) or not str(out_path).strip():
        raise _fail("out_path must be a non-empty path string")
    out = Path(str(out_path))

    check = check_confirmed_text(record, script_text)
    if check["verdict"] != "pass":
        codes = ", ".join(sorted({i["code"] for i in check["issues"]}))
        raise _fail(f"confirmed-text record fails ({codes}); nothing was overlaid")
    text = str(record["text"]).strip()

    info = _probe_video(source)
    place = _parse_placement(placement, info["width"], info["height"], info["duration"])
    font_path = _resolve_font(font_paths)

    with tempfile.TemporaryDirectory(prefix="confirmed_text_overlay_") as tmp:
        tmp_dir = Path(tmp)
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir()
        _run(
            [
                ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), str(frames_dir / "frame_%05d.png"),
            ],
            what="ffmpeg frame extraction",
        )
        frames = sorted(frames_dir.glob("frame_*.png"))
        if not frames:
            raise _fail("no frames could be extracted from the source video")
        fps = info["fps"]
        overlaid = 0
        for index, frame in enumerate(frames):
            at_s = index / fps
            if place["start_s"] <= at_s < place["end_s"]:
                _draw_text_on_frame(frame, text, place, font_path)
                overlaid += 1
        if overlaid == 0:
            raise _fail(
                "the placement window covers no source frame; check start_s/end_s "
                "against the source frame rate"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", f"{fps:.6f}", "-i", str(frames_dir / "frame_%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out),
            ],
            what="ffmpeg re-encode",
        )
        out_info = _probe_video(out)
        if abs(out_info["duration"] - info["duration"]) > 0.15:
            raise _fail(
                f"output duration {out_info['duration']:.3f}s does not match "
                f"source duration {info['duration']:.3f}s"
            )
        mid_s = (place["start_s"] + min(place["end_s"], info["duration"])) / 2
        src_frame = tmp_dir / "verify_source.png"
        out_frame = tmp_dir / "verify_output.png"
        _extract_single_frame(source, mid_s, src_frame)
        _extract_single_frame(out, mid_s, out_frame)
        changed = _placement_pixels_changed(src_frame, out_frame, place)
        if changed < 20:
            raise _fail(
                f"verification failed: only {changed} pixels changed inside "
                "the placement box; the confirmed text did not visibly land"
            )

    return {
        "ok": True,
        "verdict": "pass",
        "output_video": str(out),
        "text_id": check["text_id"],
        "version": check["version"],
        "placement": place,
        "font_used": str(font_path),
        "frames_total": len(frames),
        "frames_overlaid": overlaid,
        "source_duration_s": info["duration"],
        "output_duration_s": out_info["duration"],
        "placement_pixels_changed": changed,
        "audio": (
            "dropped: the overlay pipeline is video-only"
            if info["has_audio"]
            else "none_in_source"
        ),
        "issues": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = overlay_confirmed_text(
        params.get("source_video"),
        params.get("record"),
        params.get("script_text"),
        params.get("placement"),
        out_dir / "confirmed_text_overlay.mp4",
        font_paths=params.get("font_paths"),
    )
    report_path = out_dir / "confirmed_text_overlay.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "output_video": report["output_video"],
            "verdict": report["verdict"],
            "ok": report["ok"],
        },
    )


def register_confirmed_text_overlay_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.confirmed_text_overlay",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "source_video": {"type": "string"},
                    "record": {"type": "object"},
                    "script_text": {"type": "string"},
                    "placement": {"type": "object"},
                    "font_paths": {"type": "array"},
                },
                "required": ["source_video", "record", "script_text", "placement"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=True,
            description=(
                "Confirmed-text overlay (rain-before-stops B4, "
                "clean-room): overlays only author-confirmed wording "
                "that matches the script verbatim, in a "
                "caller-supplied placement window, with local ffmpeg "
                "frame work and a pixel-change verification. Video "
                "only; audio is not preserved. See "
                "RAIN_BEFORE_STOPS_ATTRIBUTION.md."
            ),
            line="video",
        )
    )
    return ["video.confirmed_text_overlay"]


register_confirmed_text_overlay_capabilities_once()
