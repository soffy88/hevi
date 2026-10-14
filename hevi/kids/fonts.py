"""CJK 字体解析（kids 线共用；审稿表 / 标注渲染都靠它写中文）。

CPU-only：不下载任何字体，只探测本机已安装的中文字体。优先级：
  SimHei(黑体) → Noto Sans CJK SC → WenQuanYi Zen Hei → 系统 first-match。
无任何中文字体时回落到 PIL 默认字体（此时中文会成方块，但程序不崩）。
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Optional

from PIL import ImageFont

# 已知中文字体候选（按优先级）。
_CANDIDATES = [
    "/home/soffy/.fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
]
_NAME_HINTS = ("simhei", "noto sans cjk sc", "wenquanyi", "noto serif cjk sc", "droidsansfallback")


def find_cjk_font_path() -> Optional[str]:
    """返回本机第一个可用中文字体路径（无则 None）。"""
    for c in _CANDIDATES:
        p = Path(c)
        if p.exists():
            return str(p)
    # 退化为扫描系统字体目录，按名字命中 hint。
    for pattern in ("/usr/share/fonts/**/*.tt[cf]", "/usr/share/fonts/**/*.otf",
                    "/home/soffy/.fonts/**/*.tt[cf]", "/home/soffy/.local/share/fonts/**/*.tt[cf]"):
        for p in glob.glob(pattern, recursive=True):
            low = p.lower()
            if any(h.replace(" ", "") in low.replace(" ", "") or h in Path(p).name.lower() for h in _NAME_HINTS):
                return p
    return None


def cjk_font(size: int) -> ImageFont.FreeTypeFont:
    """返回指定像素大小的 CJK 字体；无中文字体时回落到默认。"""
    fp = find_cjk_font_path()
    if fp:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()


# 模块加载时解析一次，供其它模块做 is_cjk_available 判定。
_CJK_FONT_PATH = find_cjk_font_path()


def is_cjk_available() -> bool:
    return _CJK_FONT_PATH is not None
