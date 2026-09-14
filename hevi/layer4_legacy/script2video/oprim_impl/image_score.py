"""候选图启发式打分(不读像素模型,只看容器/尺寸/魔数)。

3O 归属(待上游): `oprim.image_score`。
"""

from __future__ import annotations

import struct
from pathlib import Path

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def score_image_file_size(
    path: Path, *, sweet_min: int = 8_000, sweet_max: int = 8_000_000
) -> float:
    """合理体积靠近 1.0;过小/过大降分。"""
    if not path.exists():
        return 0.0
    size = path.stat().st_size
    if size <= 0:
        return 0.0
    if sweet_min <= size <= sweet_max:
        return 1.0
    if size < sweet_min:
        return max(0.1, size / sweet_min)
    overflow = size / sweet_max
    return max(0.2, 1.0 / overflow)


def score_image_dimensions(path: Path, *, prefer_landscape: bool = True) -> float:
    """16:9 横图最高;竖图在横屏管线里降分。读失败返回 0.5 中性。"""
    dims = _read_dimensions(path)
    if dims is None:
        return 0.5
    width, height = dims
    if width <= 0 or height <= 0:
        return 0.0
    ratio = width / height
    target = 16 / 9
    closeness = 1.0 - min(1.0, abs(ratio - target) / target)
    if prefer_landscape and height > width:
        closeness *= 0.4
    return max(0.05, closeness)


def score_image_basic(path: Path) -> float:
    """存在 + 魔数合法。"""
    if not path.exists() or path.stat().st_size <= 0:
        return 0.0
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return 0.0
    if header.startswith((_PNG_MAGIC, _JPEG_MAGIC)):
        return 1.0
    return 0.15


def _read_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data.startswith(_PNG_MAGIC) and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data.startswith(_JPEG_MAGIC):
        return _jpeg_size(data)
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    idx = 2
    length = len(data)
    while idx + 9 < length:
        if data[idx] != 0xFF:
            return None
        marker = data[idx + 1]
        if marker in {0xC0, 0xC1, 0xC2}:
            height, width = struct.unpack(">HH", data[idx + 5 : idx + 9])
            return int(width), int(height)
        block = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
        idx += 2 + block
    return None
