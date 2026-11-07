"""Free (Pexels) subject sourcing + local cutout for collage_broll."""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import json


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
        with urllib.request.urlopen(req, timeout=30) as r:
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
        with urllib.request.urlopen(r2, timeout=60) as resp:
            out_path.write_bytes(resp.read())
    except Exception:
        return None
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else None


SUBJECT_QUERIES = {
    "cat": ["orange cat", "ginger cat", "tabby cat"],
    "sea": ["ocean sea waves", "blue sea horizon", "seaside beach"],
}


def fetch_subjects(sentence: str, out_dir: Path) -> dict[str, Path | None]:
    out_dir = Path(out_dir) / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    low = sentence
    # default subjects for "橘猫看海"
    cat_path = pexels_photo("orange cat", out_dir / "cat.jpg")
    sea_path = pexels_photo("ocean sea waves", out_dir / "sea.jpg")
    return {"cat": cat_path, "sea": sea_path}


def cutout_cat(cat_path: Path | None, out_path: Path) -> Path | None:
    if cat_path is None or not Path(cat_path).exists():
        return None
    out_path = Path(out_path)
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    try:
        from PIL import Image
        from rembg import remove

        img = Image.open(cat_path).convert("RGBA")
        cut = remove(img)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cut.save(out_path)
        return out_path
    except Exception:
        return None
