"""gbro-style paper-collage renderer (offline: PIL + ffmpeg).

Style contract (ADD_COLLAGE_STYLE.md / gbro-collage-broll):
  * flat solid paper colour field as the ground
  * black-and-white halftone photographic cut-outs mounted on coloured cardstock
  * a few coloured paper accents
  * pieces slide in one by one and settle with stop-motion jitter (never a
    fade or a slow push)

Everything runs locally.  Pexels supplies the source photos; rembg (u2net,
already on the host) removes the subject background; ffmpeg encodes.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .assets import cutout_cat, pexels_photo

W, H = 720, 1280
FPS_GIF = 12
FPS_MP4 = 24
DURATION_DEFAULT = 30.0
CREAM = (245, 239, 224)
INK = (33, 30, 28)

_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

# sentence keyword -> (pexels query, paper accent, cut out the subject?)
SUBJECT_RULES: tuple[tuple[tuple[str, ...], str, str, bool], ...] = (
    (("猫", "cat"), "orange cat sitting", "#E86A33", True),
    (("海", "浪", "sea", "ocean"), "blue sea horizon", "#3FA7A0", False),
    (("视频", "剪辑", "镜头", "拍摄", "创作", "video"), "video camera", "#D9A441", True),
    (("AI", "自", "人工智能", "模型"), "robot head", "#4A3B6B", False),
    (("未来", "科技", "future"), "futuristic technology", "#2F5D50", False),
)


# ---------------------------------------------------------------------------
# Tool resolution
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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


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


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
    x0 = (img.width - w) // 2
    y0 = (img.height - h) // 2
    return img.crop((x0, y0, x0 + w, y0 + h))


def _paper_grain(img: Image.Image, amount: int = 10) -> Image.Image:
    px = img.load()
    w, h = img.size
    rng = random.Random(42)
    for y in range(h):
        for x in range(0, w, 2):
            n = rng.randint(-amount, amount)
            r, g, b = px[x, y][:3]
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return img


def _torn_mask(size: tuple[int, int], seed: int) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(mask)
    rng = random.Random(seed)
    for x in range(0, w, 16):
        r = rng.randint(1, 6)
        d.ellipse((x - r, -r, x + r, r), fill=0)
        d.ellipse((x - r, h - r, x + r, h + r), fill=0)
    for y in range(0, h, 16):
        r = rng.randint(1, 6)
        d.ellipse((-r, y - r, r, y + r), fill=0)
        d.ellipse((w - r, y - r, w + r, y + r), fill=0)
    return mask


def _halftone(photo: Image.Image, dot: int = 7, *, cutout: bool = False) -> Image.Image:
    """Black dots on white paper (scene) or transparent ground (cut-out)."""
    photo = photo.convert("RGBA")
    gray = ImageOps.autocontrast(ImageOps.grayscale(photo))
    w, h = gray.size
    cell_w = max(1, w // dot)
    cell_h = max(1, h // dot)
    small = gray.resize((cell_w, cell_h), Image.LANCZOS)
    alpha_small = (
        photo.split()[3].resize((cell_w, cell_h), Image.LANCZOS) if cutout else None
    )
    ground = (0, 0, 0, 0) if cutout else (255, 255, 255, 255)
    out = Image.new("RGBA", (w, h), ground)
    d = ImageDraw.Draw(out)
    radius = dot * 0.58
    for cy in range(cell_h):
        for cx in range(cell_w):
            if alpha_small is not None and alpha_small.getpixel((cx, cy)) < 128:
                continue
            v = small.getpixel((cx, cy))
            r = radius * (1.0 - v / 255.0)
            if r < 0.7:
                continue
            x = cx * dot + dot / 2
            y = cy * dot + dot / 2
            d.ellipse((x - r, y - r, x + r, y + r), fill=(20, 20, 20, 255))
    return out


def _photo_card(
    photo: Image.Image,
    accent: str,
    *,
    size: tuple[int, int],
    cut_out: bool,
    tilt: float = 0.0,
    seed: int = 0,
) -> Image.Image:
    """Halftone photo mounted on coloured paper with a torn edge + shadow."""
    card_w, card_h = size
    margin = 18
    window = (card_w - margin * 2, card_h - margin * 2)
    face = Image.new("RGBA", (card_w, card_h), (*_hex_to_rgb(accent), 255))
    fd = ImageDraw.Draw(face)
    if cut_out:
        subject = photo.convert("RGBA")
        maxw = window[0] - 18
        maxh = window[1] - 18
        ratio = min(maxw / max(subject.width, 1), maxh / max(subject.height, 1))
        subject = subject.resize(
            (max(1, int(subject.width * ratio)), max(1, int(subject.height * ratio))),
            Image.LANCZOS,
        )
        halftone = _halftone(subject, cutout=True)
        # white newsprint patch so the cut-out reads as a B/W photo clipping
        patch = Image.new("RGBA", (halftone.width + 16, halftone.height + 16), (250, 247, 240, 255))
        patch.alpha_composite(halftone, (8, 8))
        px = (card_w - patch.width) // 2
        py = (card_h - patch.height) // 2
        face.alpha_composite(patch, (px, py))
    else:
        image = _fit_cover(photo.convert("RGB"), window)
        halftone = _halftone(image, dot=5, cutout=False)
        face.alpha_composite(halftone, (margin, margin))
    fd.rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=12,
                         outline=(*CREAM, 255), width=4)
    # torn paper edge
    mask = _torn_mask((card_w, card_h), seed)
    face.putalpha(ImageChops.multiply(face.split()[3], mask))
    # real drop shadow, offset below-right
    shadow = Image.new("RGBA", (card_w + 40, card_h + 40), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 160), (20, 20), face.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    card = Image.new("RGBA", (card_w + 40, card_h + 40), (0, 0, 0, 0))
    card.alpha_composite(shadow, (6, 8))
    card.alpha_composite(face, (20, 20))
    card = card.crop((12, 12, 12 + card_w + 16, 12 + card_h + 16))
    if tilt:
        card = card.rotate(tilt, expand=True, resample=Image.BICUBIC)
    return card


def _accent_circle(color: str, size: int = 210) -> Image.Image:
    img = Image.new("RGBA", (size + 12, size + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, size + 6, size + 6), fill=(*_hex_to_rgb(color), 255),
              outline=(*CREAM, 255), width=6)
    return img


def _accent_strip(color: str, size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGBA", (size[0] + 12, size[1] + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, size[0] + 6, size[1] + 6), radius=6,
                        fill=(*_hex_to_rgb(color), 255), outline=(*CREAM, 255), width=3)
    return img


# ---------------------------------------------------------------------------
# Subject sourcing
# ---------------------------------------------------------------------------


def _subject_specs(sentence: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    text = sentence or ""
    for words, query, accent, cut_out in SUBJECT_RULES:
        if any(word in text for word in words):
            specs.append({"key": query.split()[0], "query": query, "accent": accent, "cut": cut_out})
    return specs[:2]


def _load_subject(spec: dict[str, Any], out_dir: Path) -> Image.Image | None:
    path = pexels_photo(spec["query"], out_dir / "assets" / f"{spec['key']}.jpg")
    if path is None or not Path(path).exists():
        return None
    if spec["cut"]:
        cut = cutout_cat(path, out_dir / "assets" / f"{spec['key']}_cutout.png")
        if cut is not None and Path(cut).exists():
            return Image.open(cut).convert("RGBA")
    return Image.open(path).convert("RGBA")


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def _tts_audio(text: str, out_path: Path) -> Path | None:
    resolved = _piper()
    if resolved is None:
        return None
    piper, voice = resolved
    raw = str(out_path) + ".raw.wav"
    try:
        proc = subprocess.run(
            [piper, "-m", str(voice), "-f", raw,
             "--length_scale", "1.0", "--sentence_silence", "0.25"],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=180,
        )
        if proc.returncode != 0 or not Path(raw).exists():
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [_ffmpeg(), "-y", "-i", raw, "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5",
             "-ar", "44100", "-ac", "2", str(out_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120,
        )
        return out_path if out_path.exists() else None
    except Exception:
        return None
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass


def _audio_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Assembly animation
# ---------------------------------------------------------------------------


def _ease_out(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def _settle(index: int, t: float, arrive: float) -> tuple[int, int, int]:
    """Slide-in offset plus 2–4 frame stop-motion settle jitter."""
    if t < arrive:
        p = _ease_out(t / max(arrive, 0.001))
        return 0, int((1 - p) * (360 + index * 130)), 0
    leftover = t - arrive
    if leftover < 0.35:  # elastic settle: 3 visible steps
        steps = [(-16, 7), (9, -4), (-4, 2), (2, -1)][: 4]
        step = min(3, int(leftover / 0.09))
        dx, dy = steps[step]
        return dx, dy, 0
    # periodic re-settle every 7s (visible stop-motion rhythm, never a fade)
    cycle = t % 7.0
    if 6.2 <= cycle < 6.7:
        p = (cycle - 6.2) / 0.5
        return 0, int(-20 * math.sin(p * math.pi)), 0
    # held collage jitter (deterministic, changes every 2 frames)
    rng = random.Random(int(t * FPS_MP4) * 31 + index * 7)
    return rng.randint(-7, 7), rng.randint(-7, 7), rng.randint(-2, 2)


def procedural_render(
    metaphor: dict[str, Any],
    out_dir: Path,
    stem: str = "clip",
    duration: float = DURATION_DEFAULT,
    narration: bool = False,
    narration_text: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sentence = str(metaphor.get("sentence") or narration_text or "橘猫看海")
    specs = _subject_specs(sentence)
    photos = [(spec, _load_subject(spec, out_dir)) for spec in specs]
    photos = [(spec, photo) for spec, photo in photos if photo is not None]
    if len(photos) == 2 and "猫" in sentence and "海" in sentence:
        # cat photo faces left; put the sea on its left so the gaze lands on it
        photos = [photos[1], photos[0]]

    # Flat paper ground: deep teal for a seaside scene, indigo for a tech/AI line.
    if any(k in sentence for k in ("猫", "海")):
        bg_hex = "#123E4C"
    elif any(k in sentence for k in ("视频", "剪辑", "AI", "未来", "科技", "创作")):
        bg_hex = "#2B2A4A"
    else:
        bg_hex = metaphor.get("background_hex", "#1E3A5F")
    bg = _paper_grain(Image.new("RGB", (W, H), _hex_to_rgb(bg_hex)), 9)
    bg_path = out_dir / "bg.png"
    bg.save(bg_path)

    # Card layout (backend avoids overlap; two-subject and three-subject grids).
    if len(photos) >= 3:
        layouts = [
            ((38, 250), (330, 430), -4),
            ((372, 160), (300, 330), 5),
            ((340, 590), (340, 300), 3),
        ]
    elif len(photos) == 2:
        layouts = [((24, 250), (390, 440), -3), ((330, 640), (330, 390), 5)]
    elif len(photos) == 1:
        layouts = [((140, 300), (450, 560), -2)]
    else:
        layouts = []

    elements: list[dict[str, Any]] = []
    short = duration <= 6.0
    for idx, ((spec, photo), (pos, size, tilt)) in enumerate(zip(photos, layouts)):
        card = _photo_card(photo, spec["accent"], size=size, cut_out=spec["cut"],
                           tilt=tilt, seed=100 + idx)
        arrive = (1.15 + idx * 0.85) if short else (0.55 + idx * 0.55)
        elements.append({"img": card, "x": pos[0], "y": pos[1],
                         "arrive": arrive, "rot": tilt})

    # Coloured paper accents (sun for the sea, tape strips otherwise).
    accents: list[dict[str, Any]] = []
    if any(k in sentence for k in ("海", "猫")):
        accents.append({"img": _accent_circle("#D95A34"), "x": W - 260, "y": 120,
                        "arrive": 0.12})
        accents.append({"img": _accent_strip("#D9A441", (150, 34)), "x": 40, "y": 170,
                        "arrive": 0.9 if duration <= 6.0 else 1.45})
    else:
        accents.append({"img": _accent_circle("#D9A441"), "x": W - 240, "y": 120,
                        "arrive": 0.12})
        accents.append({"img": _accent_strip("#3FA7A0", (180, 34)), "x": 36, "y": 150,
                        "arrive": 0.9 if duration <= 6.0 else 1.45})
    if metaphor.get("accent_colors"):
        accents.append({"img": _accent_strip(str(metaphor["accent_colors"][0]), (110, 26)),
                        "x": W - 220, "y": H - 430, "arrive": 1.1})

    text = narration_text or sentence
    font = _font(34)
    n_mp4 = max(1, int(duration * FPS_MP4))

    audio_path = out_dir / f"{stem}.wav"
    if narration:
        if _tts_audio(text, audio_path) is None:
            subprocess.run(
                [_ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                 "-t", str(duration), str(audio_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        audio_duration = _audio_duration(audio_path) or 0.0
    else:
        audio_path = None
        audio_duration = 0.0

    def _camera(frame: Image.Image, t: float) -> Image.Image:
        """Slow paper-camera drift: the held collage is never truly frozen.

        S8 saw "almost the whole clip is a still image with jitter".  A 2–5%
        zoom plus a small orbital pan reads as motion while keeping the
        stop-motion paper look; captions/credits stay pixel-fixed afterwards.
        """
        span = max(duration, 0.001)
        progress = min(1.0, t / span)
        zoom = 1.02 + 0.03 * progress
        cw, ch = max(2, int(W / zoom)), max(2, int(H / zoom))
        cx = W // 2 + int(0.010 * W * math.sin(2 * math.pi * t / 9.0))
        cy = H // 2 + int(0.008 * H * math.sin(2 * math.pi * t / 13.0))
        x0 = max(0, min(W - cw, cx - cw // 2))
        y0 = max(0, min(H - ch, cy - ch // 2))
        return frame.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BICUBIC)

    def frame_at(fi: int) -> Image.Image:
        t = fi / FPS_MP4
        frame = bg.copy().convert("RGBA")
        for idx, accent in enumerate(accents):
            dx, dy, rot = _settle(idx + 10, t, float(accent["arrive"]))
            frame.alpha_composite(accent["img"], (accent["x"] + dx, accent["y"] + dy))
        for idx, element in enumerate(elements):
            dx, dy, _rot = _settle(idx, t, float(element["arrive"]))
            frame.alpha_composite(element["img"], (element["x"] + dx, element["y"] + dy))
        frame = _camera(frame, t)
        if narration:
            bar = Image.new("RGBA", (W, 118), (0, 0, 0, 205))
            frame.alpha_composite(bar, (0, H - 118))
            d = ImageDraw.Draw(frame)
            lines = _wrap(d, text, font, W - 80)
            ty = H - 62 - 38 * min(2, len(lines))
            for line in lines[:2]:
                tw = d.textlength(line, font=font)
                d.text(((W - tw) // 2, ty), line, fill=(*CREAM, 255), font=font)
                ty += 38
        return frame.convert("RGB")

    mp4_path = out_dir / f"{stem}.mp4"
    cmd = [
        _ffmpeg(), "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS_MP4), "-i", "-",
    ]
    audio_in = ""
    if audio_path is not None and Path(audio_path).exists():
        padded = out_dir / f"{stem}_padded.wav"
        subprocess.run(
            [_ffmpeg(), "-y", "-i", str(audio_path),
             "-af", f"apad=pad_dur={max(0.0, duration - audio_duration):.3f}",
             "-t", f"{duration:.3f}", "-ar", "44100", "-ac", "2", str(padded)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        audio_in = str(padded) if padded.exists() else str(audio_path)
        cmd += ["-i", audio_in]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p"]
    if audio_in:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-t", f"{duration:.3f}"]
    else:
        cmd += ["-an"]
    cmd += [str(mp4_path)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for fi in range(n_mp4):
            proc.stdin.write(frame_at(fi).tobytes())
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else ""
        code = proc.wait(timeout=600)
    if code != 0 or not mp4_path.exists():
        raise RuntimeError(f"ffmpeg collage encode failed ({code}): {stderr[-500:]}")
    if audio_in:
        try:
            os.remove(audio_in)
        except OSError:
            pass

    gif_path = out_dir / f"{stem}.gif"
    subprocess.run(
        [_ffmpeg(), "-y", "-t", "5", "-i", str(mp4_path),
         "-vf", "fps=12,scale=360:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
         "-loop", "0", str(gif_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )

    layers_dir = out_dir / "layers"
    layers_dir.mkdir(exist_ok=True)
    for idx, element in enumerate(elements):
        try:
            element["img"].save(layers_dir / f"layer_{idx}.png")
        except Exception:
            pass

    return {
        "gif": str(gif_path),
        "mp4": str(mp4_path),
        "frames": n_mp4,
        "layers": 1 + len(elements) + len(accents),
        "duration": duration,
        "narration": narration,
        "subjects": [spec["query"] for spec, _photo in photos],
    }
