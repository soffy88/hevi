"""联络表(contact sheet)—— 把 N 帧拼成一张图,LLM/人一眼扫查(3O 内化 Phase A)。

来源: bradautomates/claude-video(抽帧输出)与 HEVI-ARCH §6.1.1 成片交付门的
"联络表"设计 —— "LLM 不看全帧看压缩表示"的成片版:每 ~6s 一帧拼图,
画面泄漏/字幕不同步/构图问题一眼可见,成本是逐帧过 VLM 的零头。

3O 归属(待上游): `oprim.build_contact_sheet`。纯 PIL 布局,无模型调用。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class ContactSheetError(Exception):
    """联络表生成失败。"""


def build_contact_sheet(
    frame_paths: list[str | Path],
    out_path: str | Path,
    *,
    cols: int = 5,
    thumb_width: int = 320,
    label_height: int = 22,
    background: tuple[int, int, int] = (12, 12, 16),
    label_color: tuple[int, int, int] = (220, 220, 230),
) -> Path:
    """把帧列表拼成网格联络表 JPEG。

    Args:
        frame_paths: 帧图片路径(顺序即时间顺序)。
        out_path: 输出 JPEG 路径。
        cols: 每行帧数(默认 5)。
        thumb_width: 单帧缩略宽度(默认 320)。
        label_height: 每格底部编号条高度。
        background / label_color: 背景与文字色。

    Returns:
        输出路径。
    """
    if not frame_paths:
        raise ContactSheetError("no frames to tile")
    paths = [Path(p) for p in frame_paths]
    cols = max(cols, 1)
    rows = (len(paths) + cols - 1) // cols

    thumbs: list[Image.Image] = []
    for p in paths:
        try:
            img = Image.open(p)
            img.load()
        except Exception as e:
            raise ContactSheetError(f"cannot open frame {p}: {e}") from e
        w, h = img.size
        ratio = thumb_width / w
        thumbs.append(img.convert("RGB").resize((thumb_width, max(1, int(h * ratio)))))

    cell_h = max((t.size[1] for t in thumbs), default=thumb_width) + label_height
    sheet_w = cols * thumb_width
    sheet_h = rows * cell_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), background)
    draw = ImageDraw.Draw(sheet)

    for idx, thumb in enumerate(thumbs):
        r, c = divmod(idx, cols)
        x, y = c * thumb_width, r * cell_h
        sheet.paste(thumb, (x, y))
        draw.text(
            (x + 4, y + thumb.size[1] + 3),
            f"#{idx + 1}",
            fill=label_color,
        )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=85)
    logger.info("contact sheet: %d frames -> %s (%dx%d)", len(paths), out, sheet_w, sheet_h)
    return out
