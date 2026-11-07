"""procedural 渲染引擎（离线，PIL + ffmpeg）。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

W, H = 720, 1280
FPS_GIF = 20
FPS_MP4 = 24
DURATION = 5.0


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
    # shadow
    shadow = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle((10, 10, w + 10, h + 10), fill=(0, 0, 0, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    layer.paste(shadow, (-10, -10), shadow)
    # main shape
    if kind == "rect":
        d.rectangle((0, 0, w - 1, h - 1), fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    elif kind == "circle":
        d.ellipse((0, 0, w - 1, h - 1), fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    elif kind == "card":
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=12, fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    else:
        d.rectangle((0, 0, w - 1, h - 1), fill=(*color, 255), outline=(245, 239, 224, 255), width=3)
    # halftone overlay
    if with_halftone:
        ht = make_halftone_layer((w, h), (0, 0, 0), 12)
        layer.alpha_composite(ht)
    return layer


def _layer_specs(metaphor: dict[str, Any]) -> list[dict[str, Any]]:
    objs = metaphor.get("key_objects", []) or ["obj1", "obj2", "obj3"]
    n = max(3, min(6, len(objs)))
    specs = []
    palette = [metaphor.get("background_hex", "#E86A33")] + (metaphor.get("accent_colors") or ["#F5EFE0"])
    # layer colors: black/white halftone + accent cards
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


def procedural_render(
    metaphor: dict[str, Any],
    out_dir: Path,
    stem: str = "clip",
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    bg_hex = metaphor.get("background_hex", "#E86A33")
    bg_path = out_dir / "bg.png"
    make_color_field(bg_hex, bg_path)
    bg = Image.open(bg_path).convert("RGBA")

    specs = _layer_specs(metaphor)
    layers: list[Image.Image] = []
    for sp in specs:
        ly = make_paper_layer(sp["kind"], sp["color"], sp["size"], sp["halftone"])
        layers.append(ly)

    # target positions (center-ish, spread)
    positions = []
    n = len(layers)
    for i in range(n):
        x = W // 2 - layers[i].width // 2 + (i - n // 2) * 40
        y = H // 2 - layers[i].height // 2 + (i % 3 - 1) * 30
        positions.append((x, y))

    nframes = int(DURATION * FPS_GIF)
    images: list[Image.Image] = []

    def composite(frame_idx: int) -> Image.Image:
        # progress 0..1
        t = frame_idx / max(1, nframes - 1)
        # clear phase at end
        clear = t > 0.85
        # number of layers visible
        # layers appear sequentially between 0.1 and 0.6
        canvas = bg.copy()
        for i, layer in enumerate(layers):
            # appearance threshold
            start = 0.1 + i * (0.5 / max(1, n - 1))
            if t < start:
                continue
            # slide-in progress
            prog = min(1.0, (t - start) / 0.15)
            if clear:
                # slide out
                out_prog = (t - 0.85) / 0.15
                off = int(out_prog * 200)
                x = positions[i][0] + off
                y = positions[i][1] + off
                alpha = max(0, 1 - out_prog)
            else:
                # slide from left
                off = int((1 - prog) * 200)
                x = positions[i][0] - off
                y = positions[i][1]
                alpha = prog
            # apply alpha to layer copy
            ly = layer.copy()
            if alpha < 1.0:
                a = ly.split()[3]
                a = a.point(lambda v: int(v * alpha))
                ly.putalpha(a)
            canvas.alpha_composite(ly, (x, y))
        return canvas.convert("RGB")

    for fi in range(nframes):
        images.append(composite(fi))

    # save GIF
    gif_path = out_dir / f"{stem}.gif"
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=int(1000 / FPS_GIF),
        loop=0,
        optimize=False,
    )

    # save frames for mp4 (24fps): resample
    tmpd = Path(tempfile.mkdtemp())
    n_mp4 = int(DURATION * FPS_MP4)
    for fi in range(n_mp4):
        # map to gif frame index
        gi = int(fi * (nframes - 1) / max(1, n_mp4 - 1))
        images[gi].save(tmpd / f"frame_{fi:04d}.png")

    mp4_path = out_dir / f"{stem}.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", str(FPS_MP4),
            "-i", str(tmpd / "frame_%04d.png"),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            str(mp4_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    # cleanup
    shutil.rmtree(tmpd, ignore_errors=True)

    # save layer pngs
    layers_dir = out_dir / "layers"
    layers_dir.mkdir(exist_ok=True)
    for i, ly in enumerate(layers):
        ly.save(layers_dir / f"layer_{i}.png")

    return {
        "gif": str(gif_path),
        "mp4": str(mp4_path),
        "frames": nframes,
        "layers": len(layers),
    }
