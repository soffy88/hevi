"""图像方向守卫（对标 ViMax image_orientation.py）。

验证生成图像为横屏（landscape），拒绝竖屏（portrait）输出。
视频管线中竖屏图像会导致画面比例异常。

提供：
  - ensure_landscape() — 验证图像方向，竖屏则抛异常
  - ensure_not_portrait() — 同上，别名
  - landscape_guard_requested() — 检查是否需要横屏守卫
  - ImageOrientationError — 方向错误
  - get_image_dimensions() — 获取图像尺寸（支持 PIL / 文件路径）
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ImageOrientationError(ValueError):
    """图像方向不符合要求。"""

    def __init__(self, width: int, height: int, message: str = ""):
        self.width = width
        self.height = height
        self.aspect_ratio = width / height if height > 0 else 0
        super().__init__(
            message or f"image is portrait ({width}x{height}, ratio={self.aspect_ratio:.2f})"
        )


@dataclass(frozen=True)
class ImageDimensions:
    """图像尺寸。"""

    width: int
    height: int

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height > 0 else 0

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def is_square(self) -> bool:
        return self.width == self.height

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000


# ── 尺寸检测 ──────────────────────────────────────────────────────────


def _read_png_dimensions(path: Path) -> tuple[int, int]:
    """从 PNG 文件头读取尺寸。"""
    with open(path, "rb") as f:
        header = f.read(24)
        if len(header) < 24:
            raise ValueError("file too small for PNG")
        # PNG IHDR chunk starts at byte 16
        width = struct.unpack(">I", header[16:20])[0]
        height = struct.unpack(">I", header[20:24])[0]
        return width, height


def _read_jpeg_dimensions(path: Path) -> tuple[int, int]:
    """从 JPEG 文件头读取尺寸（扫描 SOF 标记）。"""
    with open(path, "rb") as f:
        data = f.read()

    i = 0
    while i < len(data) - 2:
        if data[i] == 0xFF:
            marker = data[i + 1]
            # SOF markers: C0-C3, C5-C7, C9-CB, CD-CF
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if i + 9 <= len(data):
                    height = struct.unpack(">H", data[i + 5:i + 7])[0]
                    width = struct.unpack(">H", data[i + 7:i + 9])[0]
                    return width, height
                break
            elif marker == 0xD8:  # SOI
                i += 2
                continue
            elif marker == 0xD9:  # EOI
                break
            elif marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01):
                # Standalone markers
                i += 2
                continue
            else:
                # Skip segment
                if i + 3 < len(data):
                    seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
                    i += 2 + seg_len
                else:
                    break
        else:
            i += 1

    raise ValueError("could not read JPEG dimensions")


def get_image_dimensions(source: Any) -> ImageDimensions:
    """获取图像尺寸。

    支持：
      - PIL Image 对象
      - 文件路径 (Path / str)
      - numpy ndarray (HWC 格式)
      - dict {"width": W, "height": H}
    """
    # PIL Image
    if hasattr(source, "size") and hasattr(source, "mode"):
        w, h = source.size
        return ImageDimensions(width=w, height=h)

    # numpy ndarray
    if hasattr(source, "shape"):
        shape = source.shape
        if len(shape) >= 2:
            h, w = shape[0], shape[1]
            return ImageDimensions(width=w, height=h)

    # dict
    if isinstance(source, dict):
        w = source.get("width", 0)
        h = source.get("height", 0)
        return ImageDimensions(width=int(w), height=int(h))

    # 文件路径
    path = Path(source) if not isinstance(source, Path) else source
    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".png":
        w, h = _read_png_dimensions(path)
    elif suffix in (".jpg", ".jpeg"):
        w, h = _read_jpeg_dimensions(path)
    else:
        # 尝试 PIL
        try:
            from PIL import Image
            with Image.open(path) as img:
                w, h = img.size
        except ImportError:
            raise ValueError(
                f"unsupported image format: {suffix} (install Pillow for auto-detection)"
            )

    return ImageDimensions(width=w, height=h)


# ── 方向守卫 ──────────────────────────────────────────────────────────


def ensure_landscape(
    source: Any,
    *,
    min_ratio: float = 1.0,
    raise_on_square: bool = False,
) -> ImageDimensions:
    """验证图像为横屏。

    Args:
        source: 图像源（PIL/路径/ndarray/dict）
        min_ratio: 最小宽高比（默认 1.0，即宽度 > 高度）
        raise_on_square: 正方形是否也视为不合规

    Returns:
        ImageDimensions

    Raises:
        ImageOrientationError: 竖屏或正方形（若 raise_on_square=True）
    """
    dims = get_image_dimensions(source)

    if dims.is_portrait:
        raise ImageOrientationError(dims.width, dims.height)

    if raise_on_square and dims.is_square:
        raise ImageOrientationError(
            dims.width, dims.height,
            f"image is square ({dims.width}x{dims.height})"
        )

    if dims.aspect_ratio < min_ratio:
        raise ImageOrientationError(
            dims.width, dims.height,
            f"aspect ratio {dims.aspect_ratio:.2f} < min {min_ratio:.2f}"
        )

    return dims


def ensure_not_portrait(source: Any) -> ImageDimensions:
    """ensure_landscape 的别名（ViMax 兼容命名）。"""
    return ensure_landscape(source)


def landscape_guard_requested(
    *,
    aspect_ratio: str | None = None,
    width: int = 0,
    height: int = 0,
) -> bool:
    """检查是否需要启用横屏守卫。

    当明确要求横屏（16:9, 4:3 等）时返回 True。
    """
    if width > 0 and height > 0:
        return width > height

    if aspect_ratio:
        landscape_ratios = {"16:9", "4:3", "21:9", "3:2", "2:1", "1.85:1", "2.39:1"}
        portrait_ratios = {"9:16", "3:4", "2:3", "1:2"}
        if aspect_ratio in landscape_ratios:
            return True
        if aspect_ratio in portrait_ratios:
            return False

    return True  # 默认启用


def guard_image(
    source: Any,
    *,
    enforce_landscape: bool = True,
    min_ratio: float = 1.0,
    fallback_action: str = "raise",  # "raise" | "log" | "crop"
) -> ImageDimensions:
    """图像守卫主入口。

    Args:
        source: 图像源
        enforce_landscape: 是否强制横屏
        min_ratio: 最小宽高比
        fallback_action: 不合规时的处理
          - "raise": 抛异常（默认）
          - "log": 仅记录警告
          - "crop": 裁剪为横屏（需要 PIL）

    Returns:
        ImageDimensions
    """
    if not enforce_landscape:
        return get_image_dimensions(source)

    try:
        return ensure_landscape(source, min_ratio=min_ratio)
    except ImageOrientationError as e:
        if fallback_action == "raise":
            raise
        elif fallback_action == "log":
            logger.warning("landscape guard: %s", e)
            return get_image_dimensions(source)
        elif fallback_action == "crop":
            return _crop_to_landscape(source)
        else:
            raise


def _crop_to_landscape(source: Any) -> ImageDimensions:
    """裁剪图像为横屏（需要 PIL）。"""
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("PIL required for crop fallback: pip install Pillow")

    if isinstance(source, (str, Path)):
        img = Image.open(source)
    elif hasattr(source, "size"):
        img = source
    else:
        raise TypeError(f"cannot crop source type: {type(source)}")

    w, h = img.size
    if w >= h:
        return ImageDimensions(width=w, height=h)

    # 裁剪为正方形（取中心区域）
    new_w = h  # 宽度取高度值，保证横屏
    left = (w - new_w) // 2 if w > new_w else 0
    top = (h - w) // 2 if h > w else 0
    right = left + min(new_w, w)
    bottom = top + min(w, h)

    cropped = img.crop((left, top, right, bottom))
    cw, ch = cropped.size
    return ImageDimensions(width=cw, height=ch)


# ── 批量守卫 ──────────────────────────────────────────────────────────


def guard_batch(
    sources: list[Any],
    *,
    enforce_landscape: bool = True,
    strict: bool = False,
) -> list[tuple[int, ImageDimensions | None]]:
    """批量检查图像方向。

    Args:
        sources: 图像源列表
        enforce_landscape: 是否强制横屏
        strict: True = 遇竖屏立即停止; False = 收集所有结果

    Returns:
        [(index, dimensions or None), ...] — None 表示检查失败
    """
    results: list[tuple[int, ImageDimensions | None]] = []

    for i, src in enumerate(sources):
        try:
            dims = guard_image(
                src,
                enforce_landscape=enforce_landscape,
                fallback_action="raise" if strict else "log",
            )
            results.append((i, dims))
        except (ImageOrientationError, FileNotFoundError, ValueError) as e:
            logger.warning("guard_batch [%d]: %s", i, e)
            results.append((i, None))
            if strict:
                break

    return results
