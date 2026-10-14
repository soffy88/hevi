"""HyperFrames Kinetic Typography & Product Promo Compositor.

Clean-room implementation of motion-graphics / kinetic typography and product
promo videos driven by input text/specs, with local piper narration and procedural
audio, rendered deterministically via the hyperframes CLI.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

def _find_bin(name: str, fallback: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    cand = Path("/home/soffy/.local/bin") / name
    if cand.is_file():
        return str(cand)
    return fallback


FFMPEG = _find_bin("ffmpeg", "/home/soffy/.local/bin/ffmpeg")
FFPROBE = _find_bin("ffprobe", "/home/soffy/.local/bin/ffprobe")
PIPER = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
PIPER_VOICE = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"

ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "21:9": (2520, 1080),
}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{env.get('PATH', '')}"
    env["HYPERFRAMES_RENDER_DETACHED"] = "1"
    return env


def _find_hyperframes_bin() -> str:
    path = _env().get("PATH", "")
    found = shutil.which("hyperframes", path=path)
    if found:
        return found
    cand = Path("/home/soffy/.nvm/versions/node/v26.4.0/bin/hyperframes")
    if cand.is_file():
        return str(cand)
    raise RuntimeError("hyperframes CLI not found")


def synth_line(text: str, out_wav: Path, *, speed: float = 1.05) -> float:
    """Synthesise one Chinese line with local piper and apply loudnorm."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    raw = out_wav.with_suffix(".raw.wav")
    proc = subprocess.run(
        [PIPER, "-m", PIPER_VOICE, "-f", str(raw), "--length_scale", str(1 / speed), "--sentence_silence", "0.2"],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr[-400:]}")
    proc = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(raw), "-af", "highpass=f=75,loudnorm=I=-16:TP=-1.5", "-ar", "44100", "-ac", "1", str(out_wav)],
        capture_output=True,
        text=True,
    )
    raw.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm failed: {proc.stderr[-400:]}")
    out = subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_wav)]).decode().strip()
    return float(out)


def build_procedural_music(out_wav: Path, duration_s: float, *, bpm: float = 120.0) -> Path:
    """Generate a clean electronic motion beat + ambient pad using numpy."""
    sr = 44100
    total_samples = int(duration_s * sr)
    t = np.arange(total_samples) / sr
    audio = np.zeros(total_samples, dtype=np.float32)

    beat_dur = 60.0 / bpm
    total_beats = int(duration_s / beat_dur)

    # 1. Sub bass / synth pad (Minor chord: C3, Eb3, G3, Bb3 -> 130.8, 155.6, 196.0, 233.1 Hz)
    freqs = [130.81, 155.56, 196.00, 233.08]
    for i, f in enumerate(freqs):
        pad = np.sin(2 * np.pi * f * t) * (0.06 / (i + 1))
        # slow tremolo
        pad *= 0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * t + i)
        audio += pad

    # 2. Rhythmic kick & hi-hat pulses
    for b in range(total_beats):
        b_time = b * beat_dur
        b_idx = int(b_time * sr)
        if b_idx >= total_samples:
            break

        # Kick on beats 0, 2 (or every beat)
        kick_samples = min(int(0.22 * sr), total_samples - b_idx)
        if kick_samples > 0:
            kt = np.arange(kick_samples) / sr
            k_env = np.exp(-18.0 * kt)
            k_freq = 140.0 * np.exp(-22.0 * kt) + 45.0
            kick = np.sin(2 * np.pi * k_freq * kt) * k_env * 0.35
            audio[b_idx : b_idx + kick_samples] += kick

        # Hi-hat on 8th notes
        for offset_beat in (0.0, 0.5):
            hat_time = (b + offset_beat) * beat_dur
            hat_idx = int(hat_time * sr)
            hat_len = min(int(0.04 * sr), total_samples - hat_idx)
            if hat_len > 0 and hat_idx < total_samples:
                ht = np.arange(hat_len) / sr
                h_env = np.exp(-60.0 * ht)
                noise = (np.random.RandomState(int(hat_time * 1000)).uniform(-1, 1, hat_len)).astype(np.float32)
                audio[hat_idx : hat_idx + hat_len] += noise * h_env * 0.08

    # Fade out last 0.8s
    fade_len = min(int(0.8 * sr), total_samples)
    audio[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)

    audio = np.clip(audio, -0.95, 0.95)
    pcm = (audio * 32767).astype("<i2")

    import wave
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return out_wav


@dataclass
class KineticBeat:
    text: str
    sub: str = ""
    accent: str = ""
    duration_s: float = 3.0
    theme: str = "bold"  # "bold" | "accent" | "highlight" | "metric" | "outro"
    badge: str = ""


def _build_kinetic_html(
    *,
    title: str,
    beats: list[KineticBeat],
    width: int,
    height: int,
    fps: int,
    total_duration: float,
    has_audio: bool,
    product_src: str = "",
) -> str:
    # CSS & layout
    is_vertical = height > width
    is_square = height == width
    is_ultra = width / max(1, height) >= 2.0

    cards_html = []
    cursor = 0.2
    for idx, beat in enumerate(beats):
        dur = max(beat.duration_s, 1.2)
        start = cursor
        cursor += dur

        # 逐字错峰入场：标题字符在本拍前 45% 时长内依次弹入；副标题按词随后淡入
        chars = list(beat.text)
        stagger = min(0.09, (dur * 0.45) / max(1, len(chars)))
        title_spans = "".join(
            f'<span class="ch" style="animation-delay:{k * stagger:.3f}s">{escape(c) if c.strip() else "&nbsp;"}</span>'
            for k, c in enumerate(chars)
        )
        accent_delay = len(chars) * stagger + 0.1
        accent_span = (
            f'<span class="accent-word" style="animation-delay:{accent_delay:.2f}s, {accent_delay + 0.4:.2f}s; '
            f'animation-duration:0.4s, {max(0.6, dur - accent_delay - 0.8):.2f}s">'
            f'{escape(beat.accent)}</span>' if beat.accent else ""
        )
        sub_words = [w for w in beat.sub.replace("，", "， ").split(" ") if w] if beat.sub else []
        sub_html = "".join(
            f'<span class="sw" style="animation-delay:{accent_delay + 0.25 + k * 0.12:.2f}s">{escape(w)}</span>'
            for k, w in enumerate(sub_words)
        )
        sub_p = f'<p class="sub-text">{sub_html}</p>' if sub_html else ""
        badge = f'<div class="badge">{escape(beat.badge or f"{idx + 1:02d}")}</div>'
        img = (
            f'<div class="product-wrap"><img class="product" src="{escape(product_src)}" '
            f'style="animation-duration:{dur:.2f}s"/></div>' if product_src else ""
        )

        cards_html.append(
            f"""
        <section class="clip beat-card theme-{beat.theme}{' with-product' if product_src else ''}" style="animation-delay:{max(0.0, dur - 0.4):.2f}s" data-start="{start:.2f}" data-duration="{dur:.2f}" data-track-index="{idx + 1}">
          {img}
          <div class="card-inner" style="animation-duration: 0.45s, {dur:.2f}s">
            {badge}
            <h1 class="main-title">{title_spans} {accent_span}</h1>
            {sub_p}
            <div class="progress-bar"><div class="fill" style="animation-duration: {dur:.2f}s"></div></div>
          </div>
        </section>"""
        )

    audio_tags = ""
    if has_audio:
        audio_tags = f"""
      <audio id="narration" src="assets/audio/narration.wav" data-start="0" data-duration="{total_duration:.2f}" data-track-index="10"></audio>
      <audio id="sfx" src="assets/audio/music.wav" data-start="0" data-duration="{total_duration:.2f}" data-track-index="11"></audio>"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={width}, height={height}"/>
  <title>{escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: #090b10;
      color: #f3f4f6;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    }}
    #root {{
      position: relative;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: radial-gradient(circle at 50% 40%, #161b26 0%, #080a0f 100%);
    }}
    /* Grid background */
    .bg-grid {{
      position: absolute; inset: 0;
      background-size: 60px 60px;
      background-image:
        linear-gradient(to right, rgba(255,255,255,0.07) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255,255,255,0.07) 1px, transparent 1px);
      pointer-events: none;
    }}
    .bg-glow {{
      position: absolute; width: 600px; height: 600px; border-radius: 50%;
      background: radial-gradient(circle, rgba(56, 189, 248, 0.12) 0%, transparent 70%);
      top: 50%; left: 50%; transform: translate(-50%, -50%);
      pointer-events: none;
    }}
    /* Corner HUD brackets */
    .hud-corner {{
      position: absolute; width: 32px; height: 32px; border-color: rgba(56, 189, 248, 0.4); border-style: solid;
      pointer-events: none;
    }}
    .hud-tl {{ top: 36px; left: 36px; border-width: 3px 0 0 3px; }}
    .hud-tr {{ top: 36px; right: 36px; border-width: 3px 3px 0 0; }}
    .hud-bl {{ bottom: 36px; left: 36px; border-width: 0 0 3px 3px; }}
    .hud-br {{ bottom: 36px; right: 36px; border-width: 0 3px 3px 0; }}
    .watermark {{
      position: absolute; top: 40px; left: 80px; font-size: 18px; font-weight: 700;
      letter-spacing: 4px; color: rgba(255,255,255,0.4); text-transform: uppercase;
    }}

    /* Card styling */
    .clip {{
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
      padding: 60px;
    }}
    .card-inner {{
      position: relative; max-width: {'85%' if not is_vertical else '92%'}; text-align: center;
      display: flex; flex-direction: column; align-items: center; gap: 24px;
      animation-name: cardIn, slowPush;
      animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1), linear;
      animation-fill-mode: forwards, forwards;
    }}
    @keyframes slowPush {{ from {{ transform: scale(1.0) translateY(0); }} to {{ transform: scale(1.14) translateY(-18px); }} }}
    .ch {{ display: inline-block; opacity: 0; transform: translateY(60px) scale(1.6) rotate(-8deg);
          animation: charIn 0.42s cubic-bezier(0.2, 1.4, 0.4, 1) forwards; }}
    @keyframes charIn {{ to {{ opacity: 1; transform: translateY(0) scale(1) rotate(0); }} }}
    .sw {{ display: inline-block; opacity: 0; transform: translateX(-24px); margin: 0 4px;
          animation: swIn 0.35s ease-out forwards; }}
    @keyframes swIn {{ to {{ opacity: 1; transform: translateX(0); }} }}
    .accent-word {{ opacity: 0; }}
    @keyframes accentIn {{ from {{ opacity: 0; transform: scale(2.2); }} to {{ opacity: 1; transform: scale(1); }} }}
    @keyframes accentPulse {{ 0% {{ transform: scale(1); }} 25% {{ transform: scale(1.18) rotate(-3deg); }} 50% {{ transform: scale(1); }} 75% {{ transform: scale(1.18) rotate(3deg); }} 100% {{ transform: scale(1.05); }} }}
    /* 背景运动：有限时长 = 全片时长（确定性逐帧渲染下可精确定位） */
    .bg-grid {{ animation: gridPan {total_duration:.2f}s linear forwards; }}
    @keyframes gridPan {{ from {{ background-position: 0 0; }} to {{ background-position: {int(total_duration * 40)}px {int(total_duration * 20)}px; }} }}
    .bg-glow {{ width: 900px; height: 900px; animation: glowDrift {total_duration:.2f}s ease-in-out forwards; }}
    @keyframes glowDrift {{
      0% {{ transform: translate(-110%, -70%) scale(0.8); }}
      33% {{ transform: translate(10%, -30%) scale(1.3); }}
      66% {{ transform: translate(-60%, -10%) scale(1.0); }}
      100% {{ transform: translate(0%, -60%) scale(1.4); }}
    }}
    .beat-card {{ animation-name: cardOut; animation-timing-function: ease-in; animation-fill-mode: forwards; animation-duration: 0.4s; }}
    @keyframes cardOut {{ from {{ opacity: 1; transform: translateX(0) scale(1); }} to {{ opacity: 0; transform: translateX(-160px) scale(0.9); }} }}
    .product-wrap {{ position: absolute; display: flex; align-items: center; justify-content: center; overflow: hidden;
      {'left: 6%; top: 50%; width: ' + ('30%' if is_ultra else '38%') + '; height: 70%; transform: translateY(-50%);' if not is_vertical else 'left: 10%; top: 8%; width: 80%; height: 38%;'}
      border-radius: 28px; box-shadow: 0 30px 80px rgba(0,0,0,0.55); background: #111; }}
    .product {{ width: 100%; height: 100%; object-fit: cover; animation-name: kenburns; animation-timing-function: linear; animation-fill-mode: forwards; }}
    @keyframes kenburns {{ from {{ transform: scale(1.0) translate(0, 0); }} to {{ transform: scale(1.35) translate(-6%, -4%); }} }}
    .with-product {{ {'justify-content: flex-end; padding-right: ' + ('8%' if is_ultra else '5%') + ';' if not is_vertical else 'align-items: flex-end; padding-bottom: 12%;'} }}
    .with-product .card-inner {{ max-width: {'50%' if not is_vertical else '90%'}; }}
    @keyframes cardIn {{
      0% {{ opacity: 0; transform: translateY(30px) scale(0.95); }}
      100% {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}
    .badge {{
      display: inline-block; padding: 6px 18px; border-radius: 999px;
      font-size: 16px; font-weight: 800; letter-spacing: 2px;
      background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4);
    }}
    .main-title {{
      font-size: {'64px' if not is_vertical else '54px'};
      font-weight: 900; line-height: 1.25; letter-spacing: 1px;
      text-shadow: 0 4px 20px rgba(0,0,0,0.6);
    }}
    .accent-word {{
      color: #38bdf8; opacity: 0;
      background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      display: inline-block;
      animation-name: accentIn, accentPulse;
      animation-timing-function: ease-out, ease-in-out;
      animation-fill-mode: forwards, forwards;
    }}
    .sub-text {{
      font-size: {'28px' if not is_vertical else '24px'};
      color: #94a3b8; font-weight: 500; line-height: 1.5; max-width: 900px;
    }}
    .progress-bar {{
      width: 240px; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden; margin-top: 10px;
    }}
    .progress-bar .fill {{
      height: 100%; width: 100%; background: #38bdf8;
      animation: fillBar linear forwards;
    }}
    @keyframes fillBar {{
      from {{ transform: translateX(-100%); }}
      to {{ transform: translateX(0%); }}
    }}

    /* Themes */
    .theme-highlight .badge {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border-color: rgba(251, 191, 36, 0.4); }}
    .theme-highlight .accent-word {{
      background: linear-gradient(135deg, #fbbf24 0%, #f97316 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }}
    .theme-metric .badge {{ background: rgba(52, 211, 153, 0.15); color: #34d399; border-color: rgba(52, 211, 153, 0.4); }}
    .theme-metric .accent-word {{
      background: linear-gradient(135deg, #34d399 0%, #10b981 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-duration="{total_duration:.2f}" data-fps="{fps}" data-width="{width}" data-height="{height}" data-no-timeline>
    <div class="bg-grid"></div>
    <div class="bg-glow"></div>
    <div class="hud-corner hud-tl"></div>
    <div class="hud-corner hud-tr"></div>
    <div class="hud-corner hud-bl"></div>
    <div class="hud-corner hud-br"></div>
    <div class="watermark">{escape(title)}</div>
    {''.join(cards_html)}
    {audio_tags}
  </div>
</body>
</html>
"""


def render_kinetic_typography(
    *,
    output_path: Path | str,
    lines: list[tuple[str, str, str]],  # (text, sub, accent) — required, no built-in copy
    title: str = "",
    aspect_ratio: str = "16:9",
    width: int | None = None,
    height: int | None = None,
    fps: int = 30,
    with_audio: bool = True,
    product_image: str | Path | None = None,
    badges: list[str] | None = None,
) -> Path:
    """Render kinetic typography driven entirely by the caller's lines.

    Each beat: title characters fly in one by one (staggered), the accent word
    pops and pulses, sub-text words slide in, while the card slowly pushes in and
    the background grid/glow keep moving — the frame is never static.
    Raises ValueError when no lines are supplied (no placeholder copy).
    """
    if not lines or not any(str(x[0]).strip() for x in lines):
        raise ValueError("kinetic typography needs input lines (text, sub, accent); none were given")
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if aspect_ratio not in ASPECT_DIMENSIONS and (width is None or height is None):
        raise ValueError(f"unsupported aspect_ratio {aspect_ratio!r}; one of {sorted(ASPECT_DIMENSIONS)}")
    title = title or str(lines[0][0])

    w, h = ASPECT_DIMENSIONS.get(aspect_ratio, (1920, 1080))
    if width is not None and height is not None:
        w, h = width, height

    work_dir = out.parent / f".{out.stem}_kinetic_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = work_dir / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    beats: list[KineticBeat] = []
    vo_files: list[Path] = []
    total_vo_dur = 0.0

    product_src = ""
    if product_image:
        pimg = Path(product_image)
        if not pimg.is_file():
            raise ValueError(f"product_image not found: {pimg}")
        (work_dir / "assets").mkdir(parents=True, exist_ok=True)
        dst = work_dir / "assets" / f"product{pimg.suffix.lower() or '.jpg'}"
        shutil.copy2(pimg, dst)
        product_src = f"assets/{dst.name}"

    themes = ["bold", "highlight", "metric", "bold", "highlight"]
    for i, (main_text, sub_text, accent) in enumerate(lines):
        spoken = f"{main_text}，{accent}。{sub_text}" if accent else f"{main_text}。{sub_text}"
        vo_path = audio_dir / f"line_{i:02d}.wav"
        if with_audio:
            dur = synth_line(spoken, vo_path)
            vo_files.append(vo_path)
        else:
            dur = max(2.5, len(main_text) * 0.28)
        dur = max(dur + 0.35, 2.2)
        total_vo_dur += dur
        beats.append(KineticBeat(text=main_text, sub=sub_text, accent=accent, duration_s=dur,
                                 theme=themes[i % len(themes)],
                                 badge=(badges[i] if badges and i < len(badges) else "")))

    total_duration = max(total_vo_dur + 0.6, 6.0)

    # Concat vo & generate music
    if with_audio and vo_files:
        listfile = audio_dir / "vo_list.txt"
        listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in vo_files), encoding="utf-8")
        narr_wav = audio_dir / "narration.wav"
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(narr_wav)],
            check=True,
        )
        music_wav = audio_dir / "music.wav"
        build_procedural_music(music_wav, total_duration)

    # Write HTML
    html_content = _build_kinetic_html(
        title=title,
        beats=beats,
        width=w,
        height=h,
        fps=fps,
        total_duration=total_duration,
        has_audio=with_audio,
        product_src=product_src,
    )
    (work_dir / "index.html").write_text(html_content, encoding="utf-8")
    (work_dir / "hyperframes.json").write_text(json.dumps({"media": {"autoProxy": True}}, indent=2), encoding="utf-8")

    # Render via hyperframes
    hf_bin = _find_hyperframes_bin()
    silent_out = work_dir / "render_raw.mp4"
    cmd = [
        hf_bin,
        "render",
        str(work_dir),
        "-o",
        str(silent_out),
        "-f",
        str(fps),
        "-q",
        "looks",
        "--no-best-effort",
        "--quiet",
    ]
    proc = subprocess.run(cmd, cwd=str(work_dir), env=_env(), capture_output=True, text=True, timeout=1200)
    if proc.returncode != 0 or not silent_out.is_file() or silent_out.stat().st_size == 0:
        tail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:]
        raise RuntimeError(f"hyperframes render kinetic failed ({proc.returncode}):\n{tail}")

    # Ensure muxed audio with volume balancing
    if with_audio:
        narr_wav = audio_dir / "narration.wav"
        music_wav = audio_dir / "music.wav"
        mux_cmd = [
            FFMPEG, "-y", "-loglevel", "error",
            "-i", str(silent_out),
            "-i", str(narr_wav),
            "-i", str(music_wav),
            "-filter_complex", "[1:a]volume=1.0[n];[2:a]volume=0.32[m];[n][m]amix=inputs=2:duration=longest[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out),
        ]
        subprocess.run(mux_cmd, env=_env(), check=True)
    else:
        shutil.copy2(silent_out, out)

    return out


def render_product_promo(
    *,
    output_path: Path | str,
    product_name: str,
    highlights: list[dict[str, str]],
    slogan: str = "",
    cta: str = "",
    product_image: str | Path | None = None,
    aspect_ratio: str = "16:9",
    fps: int = 30,
) -> Path:
    """Product promo (15–30s) built only from the caller's product info.

    ``highlights`` = [{"title", "sub", "badge"}, ...] is required; the product
    photo (``product_image``) is shown on every beat with a slow push-in, laid
    out per aspect ratio.  No built-in product copy exists.
    """
    if not str(product_name or "").strip():
        raise ValueError("product promo needs product_name")
    if not highlights or not all(str(h.get("title", "")).strip() for h in highlights):
        raise ValueError("product promo needs at least one highlight with a title (no default selling points)")
    lines = [(product_name, slogan, "")]
    badges = ["NEW"]
    for h in highlights:
        lines.append((h["title"], h.get("sub", ""), ""))
        badges.append(h.get("badge", ""))
    if cta:
        lines.append((cta, product_name, ""))
        badges.append("")
    return render_kinetic_typography(
        output_path=output_path,
        title=product_name,
        lines=lines,
        aspect_ratio=aspect_ratio,
        fps=fps,
        with_audio=True,
        product_image=product_image,
        badges=badges,
    )


__all__ = [
    "ASPECT_DIMENSIONS",
    "build_procedural_music",
    "render_kinetic_typography",
    "render_product_promo",
    "synth_line",
]
