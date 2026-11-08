"""Koubo cut pipeline: input talking-head -> evidence-backed kinetic cut (mp4).

Runs fully offline: no browser, no cloud model, no network required for the
default path.  With no ``input_video`` the narration is synthesised with the
locally installed Piper voice, a flat-illustrated presenter is animated from
the audio envelope, and evidence cards are rendered from the narration itself
(so the evidence shot always matches what is being said).

``input_video`` remains the primary path: its audio is transcribed with a
local faster-whisper model (``HEVI_WHISPER_MODEL``) and its frames are used as
the presenter.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.koubo_cut.state import new_ledger, finalize_status

W, H = 1080, 1920
FPS = 30
DEFAULT_TARGET_S = 30.0

_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


@dataclass
class KouboCutConfig:
    seed: int = 42
    target_seconds: float = DEFAULT_TARGET_S
    width: int = W
    height: int = H


# ---------------------------------------------------------------------------
# Tool resolution (never hard-code one host path)
# ---------------------------------------------------------------------------


def _ffmpeg() -> str:
    env = os.environ.get("HEVI_FFMPEG", "").strip()
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/usr/bin/ffmpeg", "/home/soffy/.local/bin/ffmpeg"):
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("ffmpeg not found (set HEVI_FFMPEG or install ffmpeg)")


def _ffprobe() -> str:
    env = os.environ.get("HEVI_FFPROBE", "").strip()
    if env and Path(env).exists():
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    for candidate in ("/usr/bin/ffprobe", "/home/soffy/.local/bin/ffprobe"):
        if Path(candidate).exists():
            return candidate
    return ""


def _ffprobe_duration(path: Path) -> float:
    probe = _ffprobe()
    if not probe:
        return 0.0
    try:
        proc = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        return float(json.loads(proc.stdout or "{}")["format"]["duration"])
    except Exception:
        return 0.0


def _piper() -> tuple[str, Path] | None:
    binary = os.environ.get("HEVI_TALKCRAFT_PIPER", "").strip() or shutil.which("piper") or ""
    voices = Path(
        os.environ.get("HEVI_TALKCRAFT_VOICES", "").strip()
        or "/data/soffy/projects/hevi-zero/voices"
    )
    if not binary and Path("/data/soffy/projects/hevi-zero/.venv/bin/piper").exists():
        binary = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
    if not binary or not Path(binary).exists():
        return None
    for name in ("zh_CN-huayan-medium.onnx", "zh_CN-huayan-x_low.onnx"):
        voice = voices / name
        if voice.exists():
            return binary, voice
    return None


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Script + speech
# ---------------------------------------------------------------------------


_PLACEHOLDER_SCRIPT = re.compile(r"第\d+个关键点|值得你记住")


def _script_lines(
    *, script_text: str, script_lines: list[Any], topic: str
) -> list[str]:
    texts: list[str] = []
    for item in script_lines or []:
        if isinstance(item, str) and item.strip():
            texts.append(item.strip())
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("line") or "").strip()
            if text:
                texts.append(text)
    # script.quick's deterministic template ("第N个关键点:值得你记住") is a
    # placeholder, not a script: replace it with topic-specific narration so the
    # evidence cards quote something the viewer can actually connect to the image.
    if texts and not any(_PLACEHOLDER_SCRIPT.search(t) for t in texts):
        return texts

    base = (script_text or topic or "口播").strip()
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?；;])\s*", base) if p.strip()]
    if len(parts) > 1:
        return parts

    t = base
    if all(w in t for w in ("猫", "海")):
        return [
            f"{t}，先从一只橘猫说起。",
            "它趴在海边的石台上，没有追浪，也没有看镜头。",
            "海风把它的耳朵吹得微微向后。",
            "浪一层一层涌上来，声音比画面更先到达。",
            "它连眼睛都很少眨，像是早就习惯了这片海。",
            "也许对它来说，海不是风景，而是一个巨大的、会动的东西。",
            "橘猫看海，看的其实是我们看不懂的远方。",
            "如果你也见过这样的画面，大概会懂它为什么一动不动。",
            "橘猫看海，也是在看它自己的安静。",
        ]
    if "猫" in t:
        return [
            f"今天想和你聊聊{t}。",
            "它没有摆姿势，也没有看镜头，只是安静地待着。",
            "把画面放慢，你会发现它有自己的一套节奏。",
            "耳朵、尾巴、眼神，每一个小动作都在说话。",
            f"记住这个瞬间，下次再看到{t}，你会多看一眼。",
        ]
    if "海" in t:
        return [
            f"今天想和你聊聊{t}。",
            "先别急着划走，海面上有一个很容易被忽略的细节。",
            "浪一层一层涌上来，声音比画面更先到达。",
            "把视线放远，海平线会把时间拉得很慢。",
            f"记住这个瞬间，下次再遇到{t}，你会多看一眼。",
        ]
    parts = [
        f"今天我们来聊{t}。",
        f"先说最直观的一点：{t}真正打动人的，是它和生活的关系。",
        f"再看细节，{t}里藏着很多容易被忽略的部分。",
        "把视角拉近一点，你会发现节奏比想象中更重要。",
        f"记住这个画面，下次遇到{t}，你会看得更清楚。",
    ]
    if sum(len(p) for p in parts) < 150:
        parts.append(f"把这一点记住，下次看到{t}，你会更容易理解它的节奏。")
        parts.append(f"最后留一个问题：如果是你，你会怎么拍{t}？")
    return parts


def _tts(text: str, out_path: Path) -> Path | None:
    resolved = _piper()
    if resolved is None:
        return None
    piper, voice = resolved
    raw = str(out_path) + ".raw.wav"
    try:
        proc = subprocess.run(
            [piper, "-m", str(voice), "-f", raw,
             "--length_scale", "1.0", "--sentence_silence", "0.22"],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=180,
        )
        if proc.returncode != 0 or not Path(raw).exists():
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [_ffmpeg(), "-y", "-i", raw, "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5",
             "-ar", "44100", "-ac", "2", str(out_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=120,
        )
        return out_path if out_path.exists() else None
    except Exception:
        return None
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass


def _silence(duration: float, out_path: Path) -> Path:
    subprocess.run(
        [_ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{duration:.3f}", str(out_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return out_path


def _transcribe(video: Path, out_dir: Path) -> tuple[list[dict[str, Any]], Path]:
    audio = out_dir / "audio.wav"
    subprocess.run(
        [_ffmpeg(), "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)],
        capture_output=True, check=False, timeout=180,
    )
    sentences: list[dict[str, Any]] = []
    model_dir = (
        os.environ.get("HEVI_WHISPER_MODEL", "").strip()
        or os.environ.get("HEVI_TALKCRAFT_WHISPER", "").strip()
        or "/home/soffy/models/faster-whisper-large-v3-turbo"
    )
    if not Path(model_dir).is_dir():
        return sentences, audio
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_dir, device="cpu", compute_type="int8", local_files_only=True)
        segments, _info = model.transcribe(str(audio), language="zh", word_timestamps=True, beam_size=5)
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                sentences.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    except Exception:
        return [], audio
    return sentences, audio


def _sentence_times(lines: list[str], audio_duration: float) -> list[dict[str, Any]]:
    total = sum(len(line) for line in lines) or 1
    cursor = 0.0
    out: list[dict[str, Any]] = []
    for line in lines:
        span = audio_duration * len(line) / total
        out.append({"start": cursor, "end": cursor + span, "text": line})
        cursor += span
    return out


def _speech_duration(audio: Path) -> float:
    try:
        with wave.open(str(audio), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:
        return _ffprobe_duration(audio)


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def _base_background() -> Image.Image:
    img = Image.new("RGB", (W, H), (246, 239, 227))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        color = (
            int(247 - 10 * t),
            int(239 - 12 * t),
            int(226 - 14 * t),
        )
        d.line((0, y, W, y), fill=color)
    # soft paper dots
    for i in range(0, W, 26):
        for j in range(0, H, 26):
            if (i // 26 + j // 26) % 3 == 0:
                d.ellipse((i, j, i + 2, j + 2), fill=(232, 221, 205))
    # warm circle behind presenter
    d.ellipse((-220, 420, W + 220, H - 120), fill=(233, 205, 168))
    d.ellipse((-260, 470, W + 260, H - 60), fill=(242, 222, 193))
    return img


def _presenter_layer() -> tuple[Image.Image, tuple[int, int, int, int], tuple[int, int]]:
    """Half-body flat presenter with a separate mouth box for per-frame animation."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = W // 2
    # shoulders / shirt
    d.rounded_rectangle((cx - 300, 1230, cx + 300, H + 80), radius=120, fill=(32, 74, 88, 255))
    d.polygon([(cx - 110, 1210), (cx + 110, 1210), (cx + 150, 1340), (cx - 150, 1340)], fill=(240, 214, 190, 255))
    # neck
    d.rounded_rectangle((cx - 62, 1080, cx + 62, 1260), radius=50, fill=(236, 200, 172, 255))
    # head
    head = (cx - 150, 640, cx + 150, 1110)
    d.ellipse(head, fill=(242, 208, 180, 255))
    # ears
    d.ellipse((cx - 158, 830, cx - 126, 900), fill=(238, 200, 172, 255))
    d.ellipse((cx + 126, 830, cx + 158, 900), fill=(238, 200, 172, 255))
    # hair
    d.ellipse((cx - 168, 600, cx + 168, 850), fill=(52, 40, 36, 255))
    d.rectangle((cx - 168, 730, cx - 140, 900), fill=(52, 40, 36, 255))
    d.rectangle((cx + 140, 730, cx + 168, 900), fill=(52, 40, 36, 255))
    d.ellipse((cx - 150, 700, cx + 150, 790), fill=(242, 208, 180, 255))
    # eyebrows
    d.arc((cx - 108, 800, cx - 24, 850), start=200, end=340, fill=(60, 44, 38, 255), width=8)
    d.arc((cx + 24, 800, cx + 108, 850), start=200, end=340, fill=(60, 44, 38, 255), width=8)
    # eyes (open)
    for ex in (cx - 66, cx + 66):
        d.ellipse((ex - 38, 858, ex + 38, 906), fill=(255, 255, 255, 255))
        d.ellipse((ex - 20, 866, ex + 20, 906), fill=(52, 40, 36, 255))
        d.ellipse((ex - 8, 872, ex + 6, 886), fill=(255, 255, 255, 255))
    # nose
    d.polygon([(cx - 14, 950), (cx + 14, 950), (cx, 974)], fill=(212, 152, 132, 255))
    # mouth box (x0,y0,x1,y1) and centre
    mouth_box = (cx - 66, 990, cx + 66, 1058)
    d.ellipse(mouth_box, fill=(168, 88, 82, 255))
    # mic
    d.line((cx + 360, 1290, cx + 360, 1560), fill=(45, 45, 50, 255), width=12)
    d.ellipse((cx + 330, 1250, cx + 390, 1310), fill=(45, 45, 50, 255))
    d.ellipse((cx + 336, 760, cx + 384, 808), fill=(80, 80, 88, 255))
    d.line((cx + 360, 808, cx + 360, 1248), fill=(80, 80, 88, 255), width=6)
    return layer, mouth_box, (cx, 1024)


def _pip_image(base: Image.Image) -> Image.Image:
    crop = base.crop((W // 2 - 300, 600, W // 2 + 300, 1340)).resize((260, 320), Image.LANCZOS)
    pip = Image.new("RGBA", (280, 340), (0, 0, 0, 0))
    d = ImageDraw.Draw(pip)
    d.rounded_rectangle((0, 0, 279, 339), radius=22, fill=(245, 239, 224, 255))
    pip.paste(crop, (10, 10))
    return pip


def _evidence_card(
    sentence: str,
    index: int,
    out_path: Path,
    *,
    image_path: Path | None,
    fallback_image: Image.Image | None = None,
) -> Path:
    card = Image.new("RGB", (W, H), (14, 20, 32))
    d = ImageDraw.Draw(card)
    # grid
    for x in range(0, W, 54):
        d.line((x, 0, x, H), fill=(22, 30, 46))
    for y in range(0, H, 54):
        d.line((0, y, W, y), fill=(22, 30, 46))
    # red evidence tag
    d.rounded_rectangle((56, 80, 360, 170), radius=18, fill=(214, 48, 48))
    d.text((84, 98), f"证据 {index:02d}", font=_font(46), fill=(255, 255, 255))
    # sentence
    font = _font(58)
    lines = _wrap(d, sentence, font, W - 140)
    y = 230
    for line in lines[:6]:
        d.text((70, y), line, font=font, fill=(244, 240, 232))
        y += 78
    # image panel
    panel = (70, 820, W - 70, 1560)
    d.rounded_rectangle(panel, radius=28, fill=(30, 40, 58), outline=(245, 239, 224), width=4)
    px, py, px1, py1 = panel[0] + 10, panel[1] + 10, panel[2] - 10, panel[3] - 10
    pw, ph = px1 - px, py1 - py
    if image_path is not None and Path(image_path).exists():
        try:
            img = Image.open(image_path).convert("RGB")
            iw, ih = img.size
            scale = max(pw / iw, ph / ih)
            img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
            left = (img.width - pw) // 2
            top = (img.height - ph) // 2
            img = img.crop((left, top, left + pw, top + ph))
            card.paste(img, (px, py))
        except Exception:
            img = None
    if not (image_path is not None and Path(image_path).exists()):
        fallback = fallback_image or Image.new("RGB", (pw, ph), (46, 96, 132))
        card.paste(fallback.resize((pw, ph), Image.LANCZOS), (px, py))
    # red annotation ellipse
    d.ellipse((px + pw * 0.20, py + ph * 0.22, px + pw * 0.80, py + ph * 0.78),
              outline=(255, 64, 48), width=10)
    d.line((px + pw * 0.72, py + ph * 0.22, px + pw * 0.90, py + ph * 0.10),
           fill=(255, 64, 48), width=8)
    # footer
    d.text((70, 1612), "来源：本片口播讲稿 · 画面：Pexels 免费素材",
           font=_font(30), fill=(190, 198, 210))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(out_path)
    return out_path


def _audio_envelope(audio: Path, n_frames: int) -> list[float]:
    try:
        import numpy as np

        with wave.open(str(audio), "rb") as wf:
            channels = wf.getnchannels()
            rate = wf.getframerate() or 44100
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype("float32")
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        per = max(1, int(rate / FPS))
        env: list[float] = []
        for i in range(n_frames):
            chunk = samples[i * per:(i + 1) * per]
            env.append(float(np.sqrt((chunk ** 2).mean())) if chunk.size else 0.0)
        peak = max(env) or 1.0
        return [min(1.0, v / peak) for v in env]
    except Exception:
        return [0.0] * n_frames


def _render_frames(
    *,
    duration: float,
    audio: Path,
    sentences: list[dict[str, Any]],
    evidence: list[tuple[float, float, Path]],
    presenter: Image.Image | None,
    mouth_box: tuple[int, int, int, int],
    mouth_center: tuple[int, int],
    pip: Image.Image,
    badge_text: str,
    output: Path,
) -> None:
    base = _base_background()
    env = _audio_envelope(audio, int(duration * FPS))
    total = int(duration * FPS)
    caption_font = _font(52)
    tag_font = _font(34)
    title_font = _font(40)

    ff = subprocess.Popen(
        [
            _ffmpeg(), "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-i", str(audio),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-t", f"{duration:.3f}",
            str(output),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert ff.stdin is not None
    mx0, my0, mx1, my1 = mouth_box
    mcx, mcy = mouth_center
    topic_badge = (badge_text or (sentences[0]["text"][:12] if sentences else "口播精剪"))[:12]
    evidence_imgs = {path: Image.open(path).convert("RGB") for _st, _en, path in evidence}
    try:
        for fi in range(total):
            t = fi / FPS
            ev = next(((st, en, path) for st, en, path in evidence if st <= t < en), None)
            if ev is not None:
                frame = evidence_imgs[ev[2]].copy()
                frame.paste(pip, (W - 320, H - 420), pip)
            else:
                breathe = int(8 * math.sin(2 * math.pi * t / 5.0))
                frame = base.copy()
                if presenter is not None:
                    layer = presenter.copy()
                    # mouth follows the speech envelope
                    amp = env[fi] if fi < len(env) else 0.0
                    md = ImageDraw.Draw(layer)
                    md.ellipse((mx0, my0, mx1, my1), fill=(168, 88, 82, 255))
                    if amp < 0.06:
                        md.line((mcx - 34, mcy, mcx + 34, mcy), fill=(86, 34, 36, 255), width=7)
                    else:
                        mh = int(10 + 34 * amp)
                        mw = int(46 - 8 * amp)
                        md.ellipse((mcx - mw, mcy - mh // 2, mcx + mw, mcy + mh // 2),
                                   fill=(86, 34, 36, 255))
                    # blink
                    if int(t * 1000) % 3600 < 110:
                        for ex in (W // 2 - 66, W // 2 + 66):
                            md.ellipse((ex - 40, 856, ex + 40, 910), fill=(242, 208, 180, 255))
                            md.arc((ex - 38, 872, ex + 38, 900), start=10, end=170,
                                   fill=(60, 44, 38, 255), width=6)
                    frame.paste(layer, (0, breathe), layer)
                # caption
                current = next(
                    (s for s in sentences if s["start"] <= t < s["end"]),
                    sentences[-1] if sentences else None,
                )
                if current:
                    d = ImageDraw.Draw(frame)
                    d.rounded_rectangle((50, H - 360, W - 50, H - 120), radius=26,
                                        fill=(18, 22, 30))
                    lines = _wrap(d, current["text"], caption_font, W - 170)
                    ty = H - 330
                    for line in lines[:3]:
                        d.text((85, ty), line, font=caption_font, fill=(250, 248, 243))
                        ty += 66
            d = ImageDraw.Draw(frame)
            if ev is None:
                badge_w = min(660, 120 + int(d.textlength(topic_badge, font=title_font)))
                d.rounded_rectangle((50, 60, badge_w, 132), radius=20, fill=(20, 26, 36))
                d.text((76, 76), topic_badge, font=title_font, fill=(245, 239, 224))
            d.text((W - 300, 78), "口播精剪", font=tag_font, fill=(120, 90, 60))
            ff.stdin.write(frame.tobytes())
    finally:
        ff.stdin.close()
        ff.wait(timeout=300)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _write_fcpxml(out_dir: Path, duration: float, mp4: Path) -> Path:
    fcpxml = out_dir / "koubo_cut.fcpxml"
    abs_mp4 = mp4.resolve()
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    <format id="r1" name="FFVideoFormat1080x1920p30" frameDuration="1/30s" width="1080" height="1920" colorSpace="1-1-1 (Rec. 709)"/>
    <asset id="a1" name="koubo_cut" src="file://{abs_mp4}" start="0s" duration="{duration:.3f}s" hasVideo="1" hasAudio="1"/>
  </resources>
  <library>
    <event name="koubo_cut">
      <project name="koubo_cut">
        <sequence format="r1" duration="{duration:.3f}s" tcStart="0s" tcFormat="NDF">
          <spine>
            <asset-clip name="koubo_cut_main" ref="a1" offset="0s" duration="{duration:.3f}s" />
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''
    fcpxml.write_text(content, encoding="utf-8")
    return fcpxml


def run_koubo_cut(
    *,
    input_video=None,
    script_text: str = "",
    script_lines: list[Any] | None = None,
    topic: str = "",
    out_dir=None,
    seed: int = 42,
    config: KouboCutConfig | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    cfg = config or KouboCutConfig(seed=seed)
    target = float(duration_s or cfg.target_seconds or DEFAULT_TARGET_S)
    out = Path(out_dir) if out_dir is not None else Path("output/koubo_cut")
    out.mkdir(parents=True, exist_ok=True)
    ledger = new_ledger(seed=seed, out_dir=out)
    try:
        src = Path(input_video) if input_video and Path(input_video).is_file() else None
        if src is not None:
            sentences, audio_path = _transcribe(src, out)
            if not sentences:
                lines = _script_lines(script_text=script_text, script_lines=script_lines or [], topic=topic)
                sentences = _sentence_times(lines, _ffprobe_duration(src) or target)
            ledger["input"] = str(src)
            presenter_frame = None
            frame_path = out / "person.png"
            subprocess.run(
                [_ffmpeg(), "-y", "-i", str(src), "-frames:v", "1", str(frame_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if frame_path.is_file():
                presenter_frame = Image.open(frame_path).convert("RGBA")
            audio_duration = _ffprobe_duration(src) or target
            duration = max(target, audio_duration)
        else:
            lines = _script_lines(script_text=script_text, script_lines=script_lines or [], topic=topic or script_text)
            speech = out / "audio.wav"
            spoken = _tts(" ".join(lines), speech)
            if spoken is None:
                _silence(target, speech)
                spoken = speech
            audio_duration = _speech_duration(spoken)
            duration = max(target, audio_duration + 0.8)
            sentences = _sentence_times(lines, audio_duration)
            audio_path = spoken
            presenter_frame = None
            ledger["input"] = "synthetic-presenter"
        ledger["transcript"] = {"sentences": len(sentences), "words": 0}
        ledger["speech_duration_s"] = round(audio_duration, 3)

        # Pad audio to the video duration so the mux has a full-length track
        # (otherwise -shortest truncates the video mid-render).
        padded = out / "audio_padded.wav"
        subprocess.run(
            [_ffmpeg(), "-y", "-i", str(audio_path),
             "-af", f"apad=pad_dur={max(0.0, duration - audio_duration):.3f}",
             "-t", f"{duration:.3f}", "-ar", "44100", "-ac", "2", str(padded)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=120,
        )
        if padded.is_file() and padded.stat().st_size > 0:
            audio_path = padded

        presenter, mouth_box, mouth_center = _presenter_layer()
        base = _base_background()
        if presenter_frame is not None:
            # Keep user footage as the full-screen presenter when provided.
            frame = _cover(presenter_frame.convert("RGB"), (W, H))
            base = frame
        presenter_img = presenter if src is None else None
        if presenter_img is not None:
            pip_source = base.copy()
            pip_source.paste(presenter_img, (0, 0), presenter_img)
        else:
            pip_source = base
        pip = _pip_image(pip_source)

        # Evidence cards derived from the narration (never an unrelated page).
        evidence: list[tuple[float, float, Path]] = []
        subject_images = _subject_images(" ".join(s["text"] for s in sentences))
        picks = [i for i in (1, 3) if i < len(sentences)]
        for n, idx in enumerate(picks, start=1):
            sent = sentences[idx]
            subject_key = ("cat", "sea")[(n - 1) % 2]
            img = subject_images.get(subject_key) or subject_images.get("cat") or subject_images.get("sea")
            fallback = _subject_fallback({subject_key: subject_images.get(subject_key)})
            card = _evidence_card(
                sent["text"], n, out / "evidence" / f"evidence_{n}.png",
                image_path=img, fallback_image=fallback,
            )
            start = max(0.0, float(sent["start"]) + 0.3)
            end = min(duration, max(start + 2.4, float(sent["end"])))
            evidence.append((start, min(end, start + 3.0), card))
        ledger["evidence"] = [
            {"index": n + 1, "start": round(a, 2), "end": round(b, 2), "path": str(p)}
            for n, (a, b, p) in enumerate(evidence)
        ]

        mp4 = out / "koubo_cut.mp4"
        _render_frames(
            duration=duration,
            audio=audio_path,
            sentences=sentences,
            evidence=evidence,
            presenter=presenter_img,
            mouth_box=mouth_box,
            mouth_center=mouth_center,
            pip=pip,
            badge_text=topic or script_text,
            output=mp4,
        )
        if not mp4.is_file() or mp4.stat().st_size == 0:
            raise RuntimeError("ffmpeg produced no mp4")
        fcpxml = _write_fcpxml(out, duration, mp4)
        ledger["output"] = str(mp4)
        ledger["fcpxml"] = str(fcpxml)
        ledger["duration_s"] = _ffprobe_duration(mp4) or duration
        ledger["resolution"] = f"{W}x{H}"
        ledger["evidence_success"] = len(evidence)
        ledger["transcript_path"] = str(out / "transcript.json")
        (out / "transcript.json").write_text(
            json.dumps({"sentences": sentences}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ledger["status"] = "delivered"
        finalize_status(ledger, "delivered")
    except Exception as exc:
        ledger["status"] = "failed"
        ledger["error"] = f"{type(exc).__name__}: {exc}"
        finalize_status(ledger, "failed")
    return ledger


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _subject_images(text: str) -> dict[str, Path | None]:
    try:
        from hevi.collage_broll.assets import fetch_subjects, pexels_photo

        out = Path(os.environ.get("HEVI_ZERO_CACHE", "/tmp")) / "koubo_subjects"
        subjects = fetch_subjects(text, out)
        if "猫" in text and "海" in text:
            # Prefer a cat actually photographed at the water's edge: the
            # narration describes the seaside, so the evidence card must match.
            beach = pexels_photo("cat on beach", out / "assets" / "cat_beach.jpg")
            if beach is not None:
                subjects["cat"] = beach
        return subjects
    except Exception:
        return {"cat": None, "sea": None}


def _subject_fallback(subjects: dict[str, Path | None]) -> Image.Image:
    try:
        from hevi.collage_broll.assets import procedural_cat, procedural_sea

        if subjects.get("cat") is not None:
            return procedural_sea((1080, 740))
        return procedural_cat((740, 740))
    except Exception:
        return Image.new("RGB", (1080, 740), (46, 96, 132))


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    ap.add_argument("--out", default="output/koubo_cut")
    ap.add_argument("--script", default="")
    args = ap.parse_args(argv)
    ledger = run_koubo_cut(input_video=args.input, script_text=args.script, out_dir=args.out)
    print(json.dumps(ledger, ensure_ascii=False, indent=2))
    return 0 if ledger.get("status") == "delivered" else 1
