"""Executable karaoke render (``edit.karaoke_render``).

This is the execution layer below ``edit.karaoke_vertical``, which
is plan-only (per-word highlight timing, a 9:16 frame spec, caption
templates, no video). The method comes from the pdoom-video line
(mexicat MIT for the method; JohnHeibel's unlicensed version is
used for对照 only -- no code or text from either repo is copied
here): every frame is a deterministic function of song time, the
lyric timeline is word-level, and the picture reacts to the audio.

Chain, in order:
1. Word validation: sorted, non-overlapping, end > start, inside
   the declared duration -- the same rules as karaoke_vertical, so
   a bad transcript raises here too instead of being silently
   re-timed.
2. Line grouping: at most 10 words or 5 seconds per line, whichever
   comes first (the karaoke_vertical rule).
3. Audio envelope: RMS per frame window from a WAV file (stdlib
   wave), or decoded via ffmpeg for other containers. With no
   audio file the render runs in explicit ``silent_preview`` mode:
   envelope is zero and the output has no audio track -- it is
   labelled as such and must not be presented as a muxed song.
4. Frames: PIL, via ``video.code_render.render_frames`` (pure
   frame(t), per-frame SHA-256 manifest, failed-frame re-render).
   The active word is highlighted, the rest of the current line is
   shown in the base colour, and a row of audio-reactive bars plus
   a progress bar visualises the envelope.
5. Assembly: ``video.code_render.assemble_mp4`` (libx264/yuv420p,
   AAC when audio is present, ffprobe duration verified).

Tiers come from video.code_render; ``orientation: vertical``
swaps width/height (so uhd_2160p60 vertical is 2160x3840, the
4K60 target in portrait). A full-song 4K60 render is expensive by
construction -- the tests render seconds, not songs, and a caller
asking for a full song at 4K60 gets the honest cost in the result
(frame_count), not a shortcut.

Failure contract: bad words, unknown tier, an audio file that
cannot be decoded, a frame failure after retries, or a failed
ffmpeg encode all raise CapabilityError. Silent preview is never
reported as an audio mux.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.capabilities.code_render import (
    assemble_mp4,
    get_tier,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_TOL = 1e-3
_MAX_WORDS_PER_LINE = 10
_MAX_LINE_SEC = 5.0
_FONT_CANDIDATES = [
    "/home/soffy/.fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
]


def _load_font(size: int) -> Any:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001 - try next font
            continue
    return ImageFont.load_default()


def _validate_words(words_raw: Any, source_duration: float | None) -> list[dict[str, Any]]:
    if not isinstance(words_raw, list) or not words_raw:
        raise CapabilityError("edit.karaoke_render: words must be a non-empty list")
    words: list[dict[str, Any]] = []
    prev_start, prev_end = -1.0, -1.0
    for i, w in enumerate(words_raw):
        if not isinstance(w, dict):
            raise CapabilityError(f"edit.karaoke_render: word {i} must be a JSON object")
        text = w.get("word")
        if not isinstance(text, str) or not text.strip():
            raise CapabilityError(f"edit.karaoke_render: word {i}.word must be a non-empty string")
        for key in ("start_sec", "end_sec"):
            val = w.get(key)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise CapabilityError(f"edit.karaoke_render: word {i}.{key} must be a number")
        start, end = float(w["start_sec"]), float(w["end_sec"])
        if start < 0 or end <= start:
            raise CapabilityError(f"edit.karaoke_render: word {i} has an invalid time range")
        if start < prev_start - _TOL:
            raise CapabilityError(f"edit.karaoke_render: word {i} is out of order")
        if start < prev_end - _TOL:
            raise CapabilityError(f"edit.karaoke_render: word {i} overlaps the previous word")
        if source_duration is not None and end > source_duration + _TOL:
            raise CapabilityError(f"edit.karaoke_render: word {i} ends past source_duration_sec")
        prev_start, prev_end = start, end
        words.append({"word": text.strip(), "start_sec": start, "end_sec": end})
    return words


def _group_lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        trial = cur + [w]
        if cur and (len(trial) > _MAX_WORDS_PER_LINE
                    or trial[-1]["end_sec"] - trial[0]["start_sec"] > _MAX_LINE_SEC + _TOL):
            lines.append({"words": cur, "start_sec": cur[0]["start_sec"], "end_sec": cur[-1]["end_sec"]})
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append({"words": cur, "start_sec": cur[0]["start_sec"], "end_sec": cur[-1]["end_sec"]})
    return lines


def _decode_to_wav(audio_path: Path, tmp: Path) -> Path:
    if audio_path.suffix.lower() == ".wav":
        return audio_path
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CapabilityError("edit.karaoke_render: ffmpeg needed to decode non-WAV audio")
    out = tmp / "decoded.wav"
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(audio_path),
         "-ac", "1", "-ar", "22050", str(out)], capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise CapabilityError(
            f"edit.karaoke_render: could not decode audio: {(proc.stderr or '')[-300:]}")
    return out


def _envelope(audio_path: Path | None, fps: int, duration_sec: float) -> list[float]:
    count = max(1, round(duration_sec * fps))
    if audio_path is None:
        return [0.0] * count
    if not Path(audio_path).exists():
        raise CapabilityError(f"edit.karaoke_render: audio file missing: {audio_path}")
    with tempfile.TemporaryDirectory() as td:
        wav_path = _decode_to_wav(Path(audio_path), Path(td))
        with wave.open(str(wav_path), "rb") as wf:
            rate, channels, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
        if width == 2:
            samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
        elif width == 1:
            samples = [b - 128 for b in raw]
        elif width == 4:
            samples = [int(x) for x in struct.unpack(f"<{len(raw) // 4}i", raw)]
        else:
            raise CapabilityError(f"edit.karaoke_render: unsupported WAV sample width {width}")
        if channels > 1:
            samples = [sum(samples[i:i + channels]) / channels
                       for i in range(0, len(samples) - channels + 1, channels)]
        peak = max((abs(s) for s in samples), default=0) or 1
        window = max(1, int(rate / fps))
        env: list[float] = []
        for i in range(count):
            chunk = samples[i * window:(i + 1) * window]
            if not chunk:
                env.append(0.0)
            else:
                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                env.append(min(1.0, rms / (peak * 0.7) if peak else 0.0))
        return env


def build_karaoke_render(
    plan: dict[str, Any],
    tier: str = "hd_1080p60",
    orientation: str = "vertical",
    audio_path: str | Path | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("edit.karaoke_render: plan must be a JSON object")
    source_duration = plan.get("source_duration_sec")
    if source_duration is not None:
        if not isinstance(source_duration, (int, float)) or source_duration <= 0:
            raise CapabilityError("edit.karaoke_render: source_duration_sec must be > 0")
        source_duration = float(source_duration)
    words = _validate_words(plan.get("words"), source_duration)
    lines = _group_lines(words)
    duration = source_duration if source_duration is not None else words[-1]["end_sec"]
    spec = get_tier(tier)
    if orientation not in ("vertical", "horizontal"):
        raise CapabilityError("edit.karaoke_render: orientation must be 'vertical' or 'horizontal'")
    width, height = spec["width"], spec["height"]
    if orientation == "vertical":
        width, height = min(width, height), max(width, height)
    fps = spec["fps"]
    audio_mode = "silent_preview" if audio_path is None else "muxed"
    env = _envelope(Path(audio_path) if audio_path is not None else None, fps, duration)
    if out_dir is None:
        raise CapabilityError("edit.karaoke_render: out_dir is required for rendering")
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames"
    highlight = plan.get("highlight_color", "#FFD84D")
    base = plan.get("base_color", "#FFFFFF")
    title_font = _load_font(max(28, height // 24))
    word_font = _load_font(max(28, height // 22))

    def frame_fn(t: float, i: int, w: int, h: int) -> Image.Image:
        img = Image.new("RGB", (w, h), (12, 14, 22))
        d = ImageDraw.Draw(img)
        level = env[i] if i < len(env) else 0.0
        # Audio-reactive bars along the bottom.
        bars = 24
        bw = w / bars
        for b in range(bars):
            bh = int((0.08 + 0.55 * level * (0.5 + 0.5 * math.sin(b * 0.9 + t * 6.0))) * h * 0.18)
            d.rectangle([b * bw + 2, h - bh - 8, (b + 1) * bw - 2, h - 8], fill=(240, 200, 80))
        # Progress bar.
        d.rectangle([0, 0, int(w * min(1.0, t / duration)), 6], fill=(240, 200, 80))
        # Current line, active word highlighted.
        current = None
        for line in lines:
            if line["start_sec"] - 0.25 <= t < line["end_sec"] + 0.5:
                current = line
                break
        if current is None:
            current = lines[-1]
        y = int(h * 0.42)
        x = int(w * 0.08)
        for word in current["words"]:
            active = word["start_sec"] <= t < word["end_sec"]
            text = word["word"] + " "
            d.text((x, y), text, fill=highlight if active else base, font=word_font)
            # Advance by measured width (fallback: char count estimate).
            try:
                adv = d.textlength(text, font=word_font)
            except Exception:  # noqa: BLE001 - estimate then
                adv = len(text) * (h // 22)
            x += int(adv)
            if x > int(w * 0.92):
                x = int(w * 0.08)
                y += int(h * 0.07)
        d.text((int(w * 0.08), int(h * 0.08)), "karaoke render (code_render)",
               fill=(150, 160, 175), font=title_font)
        return img

    # code_render tiers are landscape sizes; render_frames validates the
    # exact size, so temporarily render at the swapped size by passing a
    # custom tier through a shim: render at the tier's fps with our own
    # width/height by drawing into the tier canvas only when sizes match.
    # For vertical tiers we therefore render via render_frames with a
    # tier whose size equals (width, height): use the matching tier name
    # when available, else fall back to direct frame loop below.
    manifest = _render_frames_sized(frame_fn, width, height, fps, duration, frames_dir)
    mp4_path = out_dir / "karaoke_render.mp4"
    assembly = assemble_mp4(
        frames_dir, fps, mp4_path,
        Path(audio_path) if audio_path is not None else None)
    result = {
        "capability": "edit.karaoke_render", "tier": tier, "orientation": orientation,
        "width": width, "height": height, "fps": fps,
        "duration_sec": duration, "word_count": len(words),
        "line_count": len(lines), "audio_mode": audio_mode,
        "frame_count": manifest["frame_count"],
        "retried_frames": manifest["retried_frames"],
        "mp4": assembly["mp4"], "mp4_bytes": assembly["bytes"],
        "mp4_duration_sec": assembly["duration_sec"],
        "frames_manifest": str(frames_dir / "manifest.json"),
    }
    (out_dir / "karaoke_render.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _render_frames_sized(frame_fn, width, height, fps, duration_sec, frames_dir):
    """Render frames at an arbitrary size with the code_render contract.

    code_render.render_frames validates against a named tier, so a
    vertical (swapped) size goes through this shim, which keeps the
    same rules: pure frame(t), per-frame SHA-256, retries, manifest.
    """
    import hashlib as _hashlib

    count = max(1, round(duration_sec * fps))
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    retried: list[int] = []
    for i in range(count):
        t = i / fps
        for attempt in range(4):
            try:
                img = frame_fn(t, i, width, height)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    raise CapabilityError(
                        f"edit.karaoke_render: frame {i} failed after 3 retries: {exc}"
                    ) from exc
                retried.append(i)
        if img.size != (width, height):
            raise CapabilityError(
                f"edit.karaoke_render: frame {i} size {img.size} != {(width, height)}")
        if img.mode != "RGB":
            img = img.convert("RGB")
        path = frames_dir / f"frame_{i:06d}.png"
        img.save(path)
        frames.append({"index": i, "t_sec": round(t, 4), "file": path.name,
                       "sha256": _hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"capability": "edit.karaoke_render", "width": width, "height": height,
                "fps": fps, "duration_sec": duration_sec, "frame_count": count,
                "retried_frames": sorted(set(retried)), "frames": frames}
    (frames_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_karaoke_render(
        params["plan"], tier=params.get("tier", "hd_1080p60"),
        orientation=params.get("orientation", "vertical"),
        audio_path=params.get("audio_path"), out_dir=out_dir)
    return CapabilityResult(
        duration_s=result["mp4_duration_sec"],
        sha256=compute_sha256(Path(result["mp4"])),
        qa={"mp4": result["mp4"], "audio_mode": result["audio_mode"],
            "frame_count": result["frame_count"], "tier": result["tier"]},
    )


def register_karaoke_render_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.karaoke_render",
        kind="video",
        aspects=["9:16", "16:9"],
        params_schema={
            "type": "object",
            "properties": {
                "plan": {"type": "object"},
                "tier": {"type": "string"},
                "orientation": {"type": "string"},
                "audio_path": {"type": "string"},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=1.5,
        render=_render,
        description=(
            "Executable karaoke render: word-level lyric timeline "
            "(karaoke_vertical rules) + audio envelope + deterministic "
            "code_render frames + ffmpeg assembly, ffprobe-verified. "
            "Tiers up to 4K60; without audio it is an explicit "
            "silent_preview, never a fake mux."
        ),
        line="edit",
    ))
    return ["edit.karaoke_render"]


register_karaoke_render_capabilities_once()
