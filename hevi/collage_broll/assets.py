"""Free (Pexels) subject sourcing + local cutout for collage_broll."""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

# Host cache ships u2net.onnx (176MB); deployments set U2NET_HOME to a
# read-only mount.  Never let rembg fall back to its 1GB bria default.
REMBG_MODEL = os.environ.get("HEVI_REMBG_MODEL", "u2net")

SUBJECT_QUERIES = {
    "cat": ("orange cat sitting", "ginger cat sitting", "orange tabby cat"),
    "sea": ("ocean sea waves", "blue sea horizon", "seaside beach"),
}


def load_pexels_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if key:
        return key
    for env_path in (Path(".env"), Path("/data/soffy/projects/hevi/.env")):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("PEXELS_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    if key:
                        os.environ["PEXELS_API_KEY"] = key
                        return key
    return ""


def pexels_photo(query: str, out_path: Path, orientation: str = "portrait") -> Path | None:
    out_path = Path(out_path)
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    key = load_pexels_key()
    if not key:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": 1, "orientation": orientation}
    )
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    photos = data.get("photos") or []
    if not photos:
        return None
    src = photos[0].get("src") or {}
    img_url = src.get("large2x") or src.get("large") or src.get("medium")
    if not img_url:
        return None
    try:
        r2 = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(r2, timeout=30) as resp:
            out_path.write_bytes(resp.read())
    except Exception:
        return None
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else None


def _subject_queries(sentence: str) -> dict[str, str]:
    text = sentence or ""
    queries: dict[str, str] = {}
    if any(w in text for w in ("猫", "cat", "Cat")):
        queries["cat"] = SUBJECT_QUERIES["cat"][0]
    if any(w in text for w in ("海", "sea", "Sea", "海边", "浪", "ocean")):
        queries["sea"] = SUBJECT_QUERIES["sea"][0]
    return queries


def fetch_subjects(sentence: str, out_dir: Path) -> dict[str, Path | None]:
    """Fetch only the subjects the sentence actually mentions.

    Falls back to ``None`` so the renderer can draw its offline paper-cut
    illustration instead of silently presenting an unrelated photo.
    """
    out_dir = Path(out_dir) / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = _subject_queries(sentence)
    result: dict[str, Path | None] = {"cat": None, "sea": None}
    for key, query in queries.items():
        result[key] = pexels_photo(query, out_dir / f"{key}.jpg")
    return result


def procedural_cat(size: tuple[int, int] = (520, 460)) -> Image.Image:
    """Offline orange-cat paper cut-out (RGBA) used when rembg/Pexels fail."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = (226, 138, 62, 255)
    dark = (186, 101, 42, 255)
    cream = (247, 230, 205, 255)
    # body
    d.ellipse((w * 0.18, h * 0.42, w * 0.82, h * 0.98), fill=body)
    # tail
    d.arc((w * 0.66, h * 0.50, w * 1.02, h * 0.92), start=-20, end=150, fill=dark, width=24)
    # head
    d.ellipse((w * 0.26, h * 0.06, w * 0.74, h * 0.56), fill=body)
    # ears
    d.polygon([(w * 0.28, h * 0.20), (w * 0.30, h * 0.00), (w * 0.44, h * 0.14)], fill=body)
    d.polygon([(w * 0.72, h * 0.20), (w * 0.70, h * 0.00), (w * 0.56, h * 0.14)], fill=body)
    d.polygon([(w * 0.31, h * 0.16), (w * 0.32, h * 0.04), (w * 0.40, h * 0.13)], fill=(238, 170, 130, 255))
    d.polygon([(w * 0.69, h * 0.16), (w * 0.68, h * 0.04), (w * 0.60, h * 0.13)], fill=(238, 170, 130, 255))
    # muzzle + eyes + nose
    d.ellipse((w * 0.36, h * 0.34, w * 0.64, h * 0.52), fill=cream)
    for ex in (0.40, 0.60):
        d.ellipse((w * ex - 16, h * 0.26 - 12, w * ex + 16, h * 0.26 + 12), fill=(35, 32, 30, 255))
        d.ellipse((w * ex - 5, h * 0.26 - 7, w * ex + 5, h * 0.26 + 3), fill=(255, 255, 255, 255))
    d.polygon([(w * 0.48, h * 0.38), (w * 0.52, h * 0.38), (w * 0.50, h * 0.42)], fill=(196, 96, 96, 255))
    d.arc((w * 0.44, h * 0.40, w * 0.50, h * 0.46), start=0, end=120, fill=(120, 70, 50, 255), width=3)
    d.arc((w * 0.50, h * 0.40, w * 0.56, h * 0.46), start=60, end=180, fill=(120, 70, 50, 255), width=3)
    # whiskers
    for dy in (-4, 6):
        d.line((w * 0.30, h * 0.40 + dy, w * 0.16, h * 0.37 + dy), fill=(60, 50, 45, 255), width=2)
        d.line((w * 0.70, h * 0.40 + dy, w * 0.84, h * 0.37 + dy), fill=(60, 50, 45, 255), width=2)
    # stripes
    for i in range(3):
        x = w * (0.34 + i * 0.10)
        d.arc((x, h * 0.52, x + w * 0.16, h * 0.70), start=250, end=290, fill=dark, width=8)
    # white paper keyline
    alpha = img.split()[3]
    dilated = alpha.filter(ImageFilter.MaxFilter(9))
    outline = Image.new("RGBA", img.size, (245, 239, 224, 255))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(outline, (0, 0), dilated)
    out.alpha_composite(img)
    return out


def procedural_sea(size: tuple[int, int]) -> Image.Image:
    """Offline layered sea (RGBA) so the collage stays on-topic with no network."""
    w, h = size
    img = Image.new("RGBA", (w, h), (78, 128, 166, 255))
    d = ImageDraw.Draw(img)
    # sky bands
    for i, color in enumerate(((133, 176, 204, 255), (110, 158, 190, 255), (92, 143, 178, 255))):
        d.rectangle((0, i * h // 8, w, (i + 1) * h // 8), fill=color)
    # sun
    d.ellipse((w * 0.62, h * 0.06, w * 0.86, h * 0.20), fill=(247, 214, 150, 255))
    # sea
    d.rectangle((0, h * 0.44, w, h), fill=(42, 96, 132, 255))
    for i in range(14):
        y = h * 0.45 + i * h * 0.04
        amp = 8 + i * 1.5
        pts = [
            (x, y + math.sin(x / (w / 6) + i) * amp)
            for x in range(0, w + 1, max(1, w // 48))
        ]
        d.line(pts, fill=(206, 228, 236, 190), width=2 + i // 5)
    # beach
    d.polygon([(0, h), (0, h * 0.90), (w * 0.35, h * 0.955), (w, h * 0.93), (w, h)], fill=(226, 201, 158, 255))
    return img


def cutout_cat(cat_path: Path | None, out_path: Path) -> Path | None:
    out_path = Path(out_path)
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if cat_path is not None and Path(cat_path).exists():
        try:
            from rembg import new_session, remove

            img = Image.open(cat_path).convert("RGBA")
            session = new_session(REMBG_MODEL)
            cut = remove(img, session=session)
            cut.save(out_path)
            return out_path
        except Exception:
            pass
    try:
        procedural_cat().save(out_path)
        return out_path
    except Exception:
        return None
