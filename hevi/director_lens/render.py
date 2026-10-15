"""CPU deterministic renderer (Director Renderer & Baseline Comparison).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont

from hevi.director_lens.brief import DirectorBrief
from hevi.director_lens.motion import sample_track
from hevi.director_lens.gate import director_check_workflow

_FONT_PATH = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
try:
    _FONT = ImageFont.truetype(_FONT_PATH, 30)
except Exception:
    _FONT = ImageFont.load_default()


def _font(size: int = 30) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except Exception:
        return _FONT


_RES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (900, 900),
}


def _render_frame_to_png(
    brief: DirectorBrief,
    t: float,
    out_path: Path,
    *,
    baseline: bool = False,
    bg_image: Image.Image | None = None,
    sub_images: dict[str, Image.Image] | None = None,
) -> None:
    width, height = _RES.get(brief.aspect, (1280, 720))
    if baseline:
        im = Image.new("RGB", (width, height), color="#2B2D42")
    elif bg_image is not None:
        im = bg_image.convert("RGB").resize((width, height))
    else:
        im = Image.new("RGB", (width, height), color="#1D3557")
    draw = ImageDraw.Draw(im)

    sub_images = sub_images or {}

    for sub in brief.subjects:
        if sub.role == "background" and not baseline:
            continue
        cx = int(sub.home_x * width)
        cy = int(sub.home_y * height)
        r = max(8, sub.size_px)
        r = int(r * (width / 1280.0))

        dx, dy = 0.0, 0.0
        sx, sy = 1.0, 1.0
        if not baseline and sub.role != "background":
            track = next((t_ for t_ in brief.tracks if t_.element == sub.id), None)
            if track:
                st = sample_track(track, t, brief.duration_s)
                dx, dy = st.dx * width, st.dy * height
                sx, sy = st.sx, st.sy
        elif baseline and sub.role != "background":
            u = min(1.0, t / max(0.1, brief.duration_s * 0.6))
            dy = -(1.0 - u) * height * 0.35
            s = 0.4 + 0.6 * u
            sx = sy = s

        x0 = int(cx + dx - r * sx)
        y0 = int(cy + dy - r * sy)
        x1 = int(cx + dx + r * sx)
        y1 = int(cy + dy + r * sy)

        color = sub.color if not baseline else "#A8DADC"
        if sub.shape == "circle":
            draw.ellipse([x0, y0, x1, y1], fill=color)
        elif sub.shape == "box":
            draw.rectangle([x0, y0, x1, y1], fill=color)
        elif sub.shape == "ring":
            draw.ellipse([x0, y0, x1, y1], outline=color, width=max(3, r // 8))
        elif sub.shape in ("bar", "drop"):
            draw.rectangle([x0, y0, x1, y1], fill=color)
        elif sub.shape == "star":
            draw.polygon(
                [(cx + dx, y0), (x0 + (x1 - x0) * 0.38, cy + dy),
                 (x0, cy + dy), (x0 + (x1 - x0) * 0.62, cy + dy + (y1 - y0) * 0.38),
                 (x1, cy + dy), (x0 + (x1 - x0) * 0.62, cy + dy + (y1 - y0) * 0.62),
                 (cx + dx, y1), (x0 + (x1 - x0) * 0.38, cy + dy + (y1 - y0) * 0.62)],
                fill=color,
            )
        else:
            draw.ellipse([x0, y0, x1, y1], fill=color)

    label = f"{brief.prompt} ({'Baseline' if baseline else 'Director'})"
    draw.text((40, 40), label, fill="#FFFFFF", font=_font(30))
    if not baseline:
        f = int(round(t * brief.fps))
        draw.text((40, height - 40), f"frame {f}/{int(brief.duration_s * brief.fps)}", fill="#FFD166", font=_font(24))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)


def _lufs_measure_audio_file(path: Path) -> tuple[float, float]:
    r = subprocess.run(
        ["ffmpeg", "-nostats", "-hide_banner", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    stderr = r.stderr or ""
    import re as _re

    m_i = _re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", stderr, _re.IGNORECASE)
    m_p = _re.search(r"Peak:\s*(-?[\d.]+) dBFS", stderr)
    lufs = float(m_i.group(1)) if m_i else -120.0
    tp = float(m_p.group(1)) if m_p else -120.0
    return lufs, tp


def _write_pcm_wav(pcm16: np.ndarray, path: Path, sr: int) -> None:
    import wave as _wave
    import numpy as np

    with _wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())


def _build_audio_wav(brief: DirectorBrief, out_path: Path, *, tmp_dir: Path | None = None) -> Path:
    import numpy as np

    SR = 44100
    n = int(round(brief.duration_s * SR)) + SR // 4
    mix = np.zeros(n, dtype=np.float64)

    mood = "calm"
    try:
        from hevi.audio.procedural_bgm import BgmConfig, synthesize_bgm

        bgm, _ = synthesize_bgm(
            BgmConfig(
                mood=mood, bpm=int(brief.bpm), duration_s=brief.duration_s,
                gain=0.45, seed=brief.seed % 1000,
            )
        )
        bgm = np.asarray(bgm, dtype=np.float64)
        if len(bgm) > len(mix):
            bgm = bgm[: len(mix)]
        mix[: len(bgm)] += bgm
    except Exception:
        pass

    sfx_dir = Path(__file__).resolve().parents[2] / "assets" / "audio" / "sfx"
    sfx_map = {
        "whoosh_air_down": "whoosh.wav",
        "whoosh_air_up": "whoosh.wav",
        "impact": "impact.wav",
        "pop": "pop.wav",
        "chime": "chime.wav",
        "ding": "ding.wav",
    }
    try:
        import soundfile as sf

        for a in brief.audio_events:
            if a.kind != "sfx" or not a.sfx_id:
                continue
            fname = sfx_map.get(a.sfx_id)
            if not fname:
                continue
            fp = sfx_dir / fname
            if not fp.exists():
                continue
            data, sr = sf.read(str(fp), dtype="float32", always_2d=False)
            if data.ndim > 1:
                data = data[:, 0]
            if sr != SR:
                idx = np.linspace(0, len(data) - 1, int(len(data) * SR / sr)).round().astype(int)
                data = data[idx]
            g = 10.0 ** (a.gain_db / 20.0)
            start = int(round(a.t * SR))
            seg = data.astype(np.float64) * g
            if start < 0:
                seg = seg[-start:]
                start = 0
            if len(seg) > 0 and start < len(mix):
                end = min(start + len(seg), len(mix))
                mix[start:end] += seg[: end - start]
    except Exception:
        pass

    rms = float(np.sqrt(np.mean(mix ** 2))) or 1.0
    mix = mix * (0.12 / rms)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tmp_dir) if tmp_dir else out_path.parent
    raw_wav = tmp_dir / f".{out_path.stem}_raw.wav"
    try:
        pcm = (np.clip(mix, -0.999, 0.999) * 32767.0).astype("<i2")
        _write_pcm_wav(pcm, raw_wav, SR)
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(raw_wav),
                "-af", "loudnorm=I=-16.0:TP=-1.8:LRA=11:linear=true",
                "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le",
                str(out_path),
            ],
            capture_output=True, text=True, check=True,
        )
    except Exception:
        _write_pcm_wav(pcm, out_path, SR)
    finally:
        if raw_wav.exists():
            raw_wav.unlink()

    return out_path


def _ffmpeg_concat(frames_dir: Path, fps: int, out_mp4: Path, *, audio_wav: Path | None = None) -> None:
    inputs = [
        "ffmpeg", "-y", "-v", "error",
        "-pattern_type", "glob",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_*.png"),
    ]
    video_args = [
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1",
        "-movflags", "+faststart",
    ]
    if audio_wav is not None and audio_wav.exists():
        cmd = inputs + [
            "-i", str(audio_wav),
        ] + video_args + [
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            str(out_mp4),
        ]
    else:
        cmd = inputs + video_args + [str(out_mp4)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def render_brief(
    brief: DirectorBrief,
    out_dir: Path | str,
    *,
    baseline: bool = False,
    bg_image: Image.Image | None = None,
    sub_images: dict[str, Image.Image] | None = None,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prefix = "baseline" if baseline else "director"
    frames_dir = out / f"{prefix}_frames"
    frames_dir.mkdir(exist_ok=True)

    fps = brief.fps
    total_frames = max(1, int(round(brief.duration_s * fps)))
    for f_idx in range(total_frames):
        t = f_idx / fps
        _render_frame_to_png(
            brief, t, frames_dir / f"frame_{f_idx:05d}.png",
            baseline=baseline, bg_image=bg_image, sub_images=sub_images,
        )

    mp4_path = out / f"{brief.id}_{prefix}.mp4"
    audio_wav = None
    if not baseline:
        audio_wav = out / f"{brief.id}_director.wav"
        _build_audio_wav(brief, audio_wav)
    _ffmpeg_concat(frames_dir, fps, mp4_path, audio_wav=audio_wav)

    sha256 = hashlib.sha256(mp4_path.read_bytes()).hexdigest()
    return {
        "mp4": str(mp4_path),
        "wav": str(audio_wav) if audio_wav is not None else None,
        "sha256": sha256,
        "duration_s": brief.duration_s,
        "baseline": baseline,
    }


def _make_baseline_brief(brief: DirectorBrief) -> DirectorBrief:
    from hevi.director_lens.brief import DirectorBrief as DB

    base = brief.to_dict()
    for t in base["tracks"]:
        t["motion"] = "linear"
        t["start_delay_frames"] = 0
    linear_events = [{"t": 0.0, "kind": "linear", "magnitude": 1.0, "params": {}}]
    for t in base["tracks"]:
        t["events"] = [dict(e) for e in linear_events]
    base["prohibitions"] = [p for p in base["prohibitions"] if "同步淡入" not in p]
    base["id"] = f"{brief.id}-baseline"
    return DB.from_dict(base)


def render_comparison_package(brief: DirectorBrief, out_dir: Path | str) -> dict[str, Any]:
    out = Path(out_dir)
    bg_image, sub_images = _load_assets_for_brief(brief)

    dir_res = render_brief(brief, out, baseline=False, bg_image=bg_image, sub_images=sub_images)
    base_brief = _make_baseline_brief(brief)
    base_res = render_brief(base_brief, out, baseline=True)

    dir_report = director_check_workflow(brief, video_path=dir_res["mp4"])
    base_report = director_check_workflow(base_brief, video_path=base_res["mp4"])

    report_data = {
        "brief_id": brief.id,
        "prompt": brief.prompt,
        "line": brief.line,
        "director_version": dir_res,
        "baseline_version": base_res,
        "director_report": dir_report,
        "baseline_report": base_report,
    }

    report_path = out / f"{brief.id}_comparison_report.json"
    report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_data


def _load_assets_for_brief(brief: DirectorBrief) -> tuple[Image.Image | None, dict[str, Image.Image]]:
    return None, {}


__all__ = ["render_brief", "render_comparison_package"]
