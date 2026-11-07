"""procedural 渲染引擎（离线，PIL + ffmpeg）。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .assets import fetch_subjects, cutout_cat

W, H = 720, 1280
FPS_GIF = 12
FPS_MP4 = 24
DURATION_DEFAULT = 30.0


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _make_grain(img: Image.Image, amount: int = 18) -> Image.Image:
    import random

    px = img.load()
    w, h = img.size
    rng = random.Random(42)
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            n = rng.randint(-amount, amount)
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return img


def make_color_field(hex_color: str, out: Path) -> Path:
    rgb = _hex_to_rgb(hex_color)
    img = Image.new("RGB", (W, H), rgb)
    img = _make_grain(img, 12)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def make_halftone_layer(size: tuple[int, int], dot_color: tuple[int, int, int], spacing: int = 14) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(0, h, spacing):
        for x in range(0, w, spacing):
            r = 3
            d.ellipse((x - r, y - r, x + r, y + r), fill=(*dot_color, 200))
    return img


def make_paper_layer(
    kind: str,
    color: tuple[int, int, int],
    size: tuple[int, int],
    with_halftone: bool = True,
) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    shadow = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle((10, 10, w + 10, h + 10), fill=(0, 0, 0, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    layer.paste(shadow, (-10, -10), shadow)
    if kind == "rect":
        d.rectangle((0, 0, w - 1, h - 1), fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    elif kind == "circle":
        d.ellipse((0, 0, w - 1, h - 1), fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    elif kind == "card":
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=12, fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    else:
        d.rectangle((0, 0, w - 1, h - 1), fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    if with_halftone:
        ht = make_halftone_layer((w, h), (0, 0, 0), 12)
        layer.alpha_composite(ht)
    return layer


def _layer_specs(metaphor: dict[str, Any]) -> list[dict[str, Any]]:
    objs = metaphor.get("key_objects", []) or ["obj1", "obj2", "obj3"]
    n = max(3, min(6, len(objs)))
    specs = []
    kinds = ["rect", "circle", "card", "rect", "circle", "card"]
    for i in range(n):
        if i % 2 == 0:
            color = (43, 43, 43)
            ht = True
        else:
            color = _hex_to_rgb(metaphor.get("accent_colors", ["#D9A441"])[0] if metaphor.get("accent_colors") else "#D9A441")
            ht = False
        w = 120 + (i * 37 % 80)
        h = 90 + (i * 29 % 60)
        specs.append({"kind": kinds[i % len(kinds)], "color": color, "size": (w, h), "halftone": ht, "name": f"layer_{i}"})
    return specs


def _tts_audio(text: str, out_path: Path) -> Path | None:
    out_path = Path(out_path)
    piper = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
    voices = "/data/soffy/projects/hevi-zero/voices"
    voice = "zh_CN-huayan-medium.onnx"
    voice_path = Path(voices) / voice
    if not Path(piper).exists() or not voice_path.exists():
        return None
    raw = str(out_path) + ".raw.wav"
    try:
        proc = subprocess.run(
            [piper, "-m", str(voice_path), "-f", raw, "--length_scale", "1.0", "--sentence_silence", "0.25"],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode != 0 or not Path(raw).exists():
            return None
        subprocess.run(
            ["/home/soffy/.local/bin/ffmpeg", "-y", "-i", raw, "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5", "-ar", "44100", "-ac", "2", str(out_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        try:
            os.remove(raw)
        except OSError:
            pass
        return out_path if out_path.exists() else None
    except Exception:
        return None


def _load_image(path: Path | None, fallback_color: tuple[int, int, int]) -> Image.Image:
    if path is not None and Path(path).exists():
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            pass
    img = Image.new("RGB", (W, H), fallback_color)
    return _make_grain(img, 12)


def _fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return img.crop((x0, y0, x0 + w, y0 + h))


def _add_outline(img: Image.Image, outline_px: int = 8, color=(245, 239, 224, 255)) -> Image.Image:
    # img RGBA cutout
    alpha = img.split()[3]
    dilated = alpha.filter(ImageFilter.MaxFilter(outline_px * 2 + 1))
    outline = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(outline)
    # fill dilated region white-ish behind
    mask = dilated
    base = Image.new("RGBA", img.size, color)
    outline.paste(base, (0, 0), mask)
    # remove original alpha region to keep outline only
    orig_mask = alpha
    # zero out where original present
    inv = Image.new("L", img.size, 255)
    # subtract original alpha
    import PIL.ImageChops as chops

    diff = chops.subtract(dilated, alpha)
    outline2 = Image.new("RGBA", img.size, (0, 0, 0, 0))
    base2 = Image.new("RGBA", img.size, color)
    outline2.paste(base2, (0, 0), diff)
    # composite original on top
    out = outline2.copy()
    out.alpha_composite(img)
    return out


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
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    bg_hex = metaphor.get("background_hex", "#1E3A5F")
    bg_path = out_dir / "bg.png"
    make_color_field(bg_hex, bg_path)

    # source images
    sentence = metaphor.get("sentence", "") or narration_text or "橘猫看海"
    subjects = fetch_subjects(sentence, out_dir)
    cat_cut_path = cutout_cat(subjects.get("cat"), out_dir / "assets" / "cat_cutout.png")

    sea_img = _load_image(subjects.get("sea"), (30, 80, 140))
    sea_cover = _fit_cover(sea_img, (W + 120, H + 120))

    if cat_cut_path is not None and Path(cat_cut_path).exists():
        try:
            cat_img = Image.open(cat_cut_path).convert("RGBA")
        except Exception:
            cat_img = None
    else:
        cat_img = None
    if cat_img is None:
        # fallback: solid cat-ish blob
        cat_img = Image.new("RGBA", (300, 260), (200, 120, 60, 255))
    # resize cat
    maxw = 360
    if cat_img.width > maxw:
        ratio = maxw / cat_img.width
        cat_img = cat_img.resize((maxw, int(cat_img.height * ratio)), Image.LANCZOS)
    cat_layer = _add_outline(cat_img, 6)

    halftone = make_halftone_layer((W, H), (0, 0, 0), 16)

    # paper grain overlay
    grain = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grain)
    import random

    rng = random.Random(7)
    for _ in range(1200):
        x = rng.randrange(W)
        y = rng.randrange(H)
        gd.point((x, y), fill=(245, 239, 224, rng.randint(20, 70)))

    text = narration_text or sentence
    # font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except Exception:
        font = ImageFont.load_default()

    n_mp4 = int(duration * FPS_MP4)
    images: list[Image.Image] = []

    def frame_at(fi: int) -> Image.Image:
        t = fi / max(1, n_mp4 - 1)
        # sea pan
        sx = int(60 * math.sin(t * math.pi * 2))
        sy = int(20 * math.sin(t * math.pi))
        sea_crop = sea_cover.crop((sx, sy, sx + W, sy + H)).convert("RGBA")
        # slight color tint
        canvas = sea_crop.copy()
        # cat parallax
        cx = (W - cat_layer.width) // 2 + int(30 * math.sin(t * math.pi * 2 + 0.5))
        cy = (H - cat_layer.height) // 2 + 120 + int(15 * math.sin(t * math.pi))
        canvas.alpha_composite(cat_layer, (cx, cy))
        # halftone overlay (semi)
        ht = halftone.copy()
        a = ht.split()[3]
        a = a.point(lambda v: int(v * 0.35))
        ht.putalpha(a)
        canvas.alpha_composite(ht, (0, 0))
        # grain paper
        canvas.alpha_composite(grain, (0, 0))
        # subtitle
        if narration:
            # bottom bar
            bar = Image.new("RGBA", (W, 120), (0, 0, 0, 120))
            canvas.alpha_composite(bar, (0, H - 120))
            d = ImageDraw.Draw(canvas)
            # center text
            bbox = d.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            d.text(((W - tw) // 2, H - 80), text, fill=(245, 239, 224, 255), font=font)
        return canvas.convert("RGB")

    for fi in range(n_mp4):
        images.append(frame_at(fi))

    # save frames
    tmpd = Path(tempfile.mkdtemp())
    for fi, im in enumerate(images):
        im.save(tmpd / f"frame_{fi:04d}.png")

    # TTS audio
    audio_path = out_dir / f"{stem}.wav"
    if narration:
        res_audio = _tts_audio(text, audio_path)
        if res_audio is None:
            # generate silence
            subprocess.run(
                ["/home/soffy/.local/bin/ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", "-t", str(duration), str(audio_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
    else:
        audio_path = None

    mp4_path = out_dir / f"{stem}.mp4"
    if narration and audio_path is not None and Path(audio_path).exists():
        # pad audio to duration
        padded = out_dir / f"{stem}_padded.wav"
        subprocess.run(
            ["/home/soffy/.local/bin/ffmpeg", "-y", "-i", str(audio_path), "-af", f"apad=pad_dur={duration}", "-t", str(duration), str(padded)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        audio_in = str(padded) if padded.exists() else str(audio_path)
        subprocess.run(
            [
                "/home/soffy/.local/bin/ffmpeg", "-y",
                "-framerate", str(FPS_MP4),
                "-i", str(tmpd / "frame_%04d.png"),
                "-i", audio_in,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                str(mp4_path),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
        try:
            if padded.exists():
                os.remove(padded)
        except OSError:
            pass
    else:
        subprocess.run(
            [
                "/home/soffy/.local/bin/ffmpeg", "-y",
                "-framerate", str(FPS_MP4),
                "-i", str(tmpd / "frame_%04d.png"),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an",
                str(mp4_path),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )

    # gif (short preview, first min(duration,5)s)
    gif_frames = min(n_mp4, int(5 * FPS_MP4))
    gif_path = out_dir / f"{stem}.gif"
    try:
        images[0].save if False else None
    except Exception:
        pass
    try:
        # build gif from first gif_frames images at 12fps mapping
        gi_imgs = [images[int(i * (n_mp4 - 1) / max(1, gif_frames - 1))] for i in range(gif_frames)]
        # resize for gif
        gi_imgs = [im.resize((360, 640)) for im in gi_imgs]
        gi_imgs[0].save(
            gif_path,
            save_all=True,
            append_images=gi_imgs[1:],
            duration=int(1000 / 12),
            loop=0,
            optimize=True,
        )
    except Exception:
        pass

    shutil.rmtree(tmpd, ignore_errors=True)

    layers_dir = out_dir / "layers"
    layers_dir.mkdir(exist_ok=True)
    try:
        cat_layer.save(layers_dir / "layer_cat.png")
    except Exception:
        pass

    sha = hashlib.sha256()
    try:
        import hashlib as _h

        sha = _h.sha256(Path(mp4_path).read_bytes()).hexdigest()
    except Exception:
        sha = ""

    return {
        "gif": str(gif_path) if gif_path.exists() else str(gif_path),
        "mp4": str(mp4_path),
        "frames": n_mp4,
        "layers": 4,
        "duration": duration,
        "narration": narration,
    }
