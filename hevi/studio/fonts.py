"""已拉取的字幕/手写字体。"""

from __future__ import annotations

from pathlib import Path

from hevi.studio.voices import asset_root

_FONT_EXTS = (".ttf", ".otf")
_PACKS = ("subtitle-fonts", "handwrite-font")


def list_fonts(*, root: Path | None = None) -> list[Path]:
    base = root or asset_root()
    found: list[Path] = []
    for pack in _PACKS:
        folder = base / pack
        if not folder.is_dir():
            continue
        found.extend(sorted(p for p in folder.rglob("*") if p.suffix.lower() in _FONT_EXTS))
    return found


def resolve_font(name: str, *, root: Path | None = None) -> Path | None:
    needle = (name or "").strip().lower()
    if not needle:
        return None
    direct = Path(name)
    if direct.is_file():
        return direct
    aliases = {
        "handwrite": "patrickhand",
        "hand": "patrickhand",
        "charm": "charm-regular",
        "vietnam": "bevietnampro-medium",
    }
    needle = aliases.get(needle, needle)
    for path in list_fonts(root=root):
        if needle in path.stem.lower().replace(" ", ""):
            return path
    return None
