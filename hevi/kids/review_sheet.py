"""review_sheet —— 分镜审稿表网格 PNG 渲染（RENOISE_EVAL §3.4 / K2 交付物 1）。

从 manifest（经 manifest_adapter 适配点）+ ShotSpec 渲染一集一张网格图：
  - 每格：左上镜号 S{n}、右上时长 {duration}s、中部缩略图（缺关键帧→灰底占位）、
    下部台词一行 + 机位/景别一行；
  - 页脚：第{episode}集《{title}》｜主题｜总时长｜N 镜；
  - 9:16（竖屏）与 16:9 各出一张；PDF 可选。

**只用于人工/审稿预览，不作为生成输入**（对齐 storyboard-sheet A 模式）。
确定性：同一输入两次输出像素级一致（无随机、无时间戳，PNG 字节可复现）。

复用：``hevi/ingest/contact_sheet.py`` 的网格拼接思路 + 本模块自带的 CJK 字体
（``hevi/kids/fonts.py``）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .fonts import cjk_font

# 审稿表只用这两个比例（§3.4）。
ASPECT_PORTRAIT = "9:16"
ASPECT_LANDSCAPE = "16:9"

# 每比例的画布尺寸与每行列数。
_SHEET_SIZE = {
    ASPECT_PORTRAIT: (720, 1280),
    ASPECT_LANDSCAPE: (1280, 720),
}
_SHEET_COLS = {
    ASPECT_PORTRAIT: 2,
    ASPECT_LANDSCAPE: 3,
}

BG = (18, 18, 24)
PANEL_BG = (30, 30, 38)
PLACEHOLDER = (90, 90, 100)
TEXT = (235, 235, 240)
MUTED = (170, 170, 180)
ACCENT = (255, 214, 120)
FOOTER_BG = (12, 12, 16)


class ReviewSheetError(Exception):
    """审稿表渲染失败。"""


def _truncate(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _draw_panel(
    canvas_img: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    shot: Any,
    *,
    cjk: Any,
) -> None:
    x0, y0, x1, y1 = box
    cell_w = x1 - x0
    cell_h = y1 - y0

    # 面板底
    draw.rectangle(box, fill=PANEL_BG, outline=ACCENT, width=2)

    # 左上：镜号
    draw.text((x0 + 8, y0 + 6), f"S{shot.shot_index}", fill=ACCENT, font=cjk)
    # 右上：时长（±0.05s 精度：2 位小数）
    dur = f"{shot.duration:.2f}s"
    draw.text((x1 - 8 - draw.textlength(dur, font=cjk), y0 + 6), dur, fill=TEXT, font=cjk)

    # 中部：缩略图区域
    thumb_top = y0 + 34
    thumb_bottom = y1 - int(cell_h * 0.35)
    thumb_box = (x0 + 8, thumb_top, x1 - 8, thumb_bottom)
    draw.rectangle(thumb_box, fill=(8, 8, 12))
    kf = shot.keyframe
    pasted = False
    if kf:
        p = Path(kf)
        if p.exists():
            try:
                thumb_img = Image.open(p).convert("RGB")
                tw = thumb_box[2] - thumb_box[0]
                th = thumb_box[3] - thumb_box[1]
                thumb_img.thumbnail((tw, th))
                iw, ih = thumb_img.size
                canvas_img.paste(thumb_img, (thumb_box[0] + (tw - iw) // 2, thumb_box[1] + (th - ih) // 2))
                pasted = True
            except Exception:
                pasted = False
    if not pasted:
        # 灰底占位（缺关键帧或解码失败都不崩）
        draw.rectangle(thumb_box, fill=PLACEHOLDER)
        ph = "无关键帧"
        draw.text(
            (thumb_box[0] + (thumb_box[2] - thumb_box[0] - draw.textlength(ph, font=cjk)) // 2,
             thumb_box[1] + (thumb_box[3] - thumb_box[1] - 14) // 2),
            ph,
            fill=TEXT,
            font=cjk,
        )

    # 下部：台词一行（按像素宽度量截断）
    max_w = cell_w - 24
    line_text = shot.line or "（无台词）"
    while draw.textlength(line_text, font=cjk) > max_w and len(line_text) > 1:
        line_text = line_text[:-1]
    if line_text != (shot.line or "（无台词）") and not line_text.endswith("…"):
        if len(line_text) > 1:
            line_text = line_text[:-1] + "…"

    fs = int(min(cell_w, cell_h) * 0.055)
    line_y = y1 - int(cell_h * 0.28)
    cam_y = y1 - int(cell_h * 0.14)

    draw.text((x0 + 8, line_y), line_text, fill=TEXT, font=cjk)
    # 机位 / 景别一行
    cam = shot.camera or "—"
    fram = shot.framing or "—"
    cam_line = f"机位:{cam} 景别:{fram}"
    while draw.textlength(cam_line, font=cjk) > max_w and len(cam_line) > 1:
        cam_line = cam_line[:-1]
    draw.text((x0 + 8, cam_y), cam_line, fill=MUTED, font=cjk)


def render_review_sheet(
    manifest: Any,
    out_path: str | Path,
    aspect: str,
    *,
    pdf: bool = False,
) -> Path:
    """渲染一张网格审稿表 PNG（可选 PDF）。返回输出路径。

    Args:
        manifest: ManifestProtocol（经 manifest_adapter.load_manifest 得到）。
        out_path: 输出路径（.png；pdf=True 时同时写出同名 .pdf）。
        aspect: "9:16" 或 "16:9"。
        pdf: 是否额外导出 PDF。
    """
    if aspect not in _SHEET_SIZE:
        raise ReviewSheetError(f"unsupported aspect {aspect!r} (need 9:16 or 16:9)")
    from .manifest_adapter import ManifestProtocol

    if not isinstance(manifest, ManifestProtocol):
        raise ReviewSheetError("manifest must be loaded via manifest_adapter")

    shots = manifest.shots()
    if not shots:
        raise ReviewSheetError("manifest 没有 shots，无法渲染审稿表")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    sheet_w, base_sheet_h = _SHEET_SIZE[aspect]
    cols = _SHEET_COLS[aspect]
    rows = (len(shots) + cols - 1) // cols

    # 页脚高度固定，动态计算 grid 高度防崩（N=30 适应高网格）
    footer_h = 40
    min_cell_h = 180 if aspect == ASPECT_PORTRAIT else 160
    grid_h = max(base_sheet_h - footer_h, rows * min_cell_h)
    sheet_h = grid_h + footer_h
    cell_w = sheet_w // cols
    cell_h = grid_h // rows

    cjk = cjk_font(int(min(cell_w, cell_h) * 0.06))

    img = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(img)

    for idx, shot in enumerate(shots):
        r, c = divmod(idx, cols)
        box = (c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
        pad = 4
        _draw_panel(
            img,
            draw,
            (box[0] + pad, box[1] + pad, box[2] - pad, box[3] - pad),
            shot,
            cjk=cjk,
        )

    # 页脚
    draw.rectangle((0, sheet_h - footer_h, sheet_w, sheet_h), fill=FOOTER_BG)
    theme = manifest.theme().get("one_line", "")
    footer = (
        f"第{manifest.episode()}集《{manifest.title()}》｜主题：{theme}"
        f"｜总时长 {manifest.total_duration():.2f}s｜{len(shots)} 镜"
    )
    footer_font = cjk
    while draw.textlength(footer, font=footer_font) > sheet_w - 16 and footer_font.size > 10:
        footer_font = cjk_font(footer_font.size - 1)
    if draw.textlength(footer, font=footer_font) > sheet_w - 16:
        footer = _truncate(footer, int(sheet_w / 12))
    draw.text((8, sheet_h - footer_h + 12), footer, fill=TEXT, font=footer_font)

    img.save(out, "PNG")
    if pdf:
        out_pdf = out.with_suffix(".pdf")
        img.save(out_pdf, "PDF", resolution=72.0)

    return out


def review_sheet_sha256(out_path: str | Path) -> str:
    return hashlib.sha256(Path(out_path).read_bytes()).hexdigest()


def render_both_aspects(
    manifest: Any,
    out_dir: str | Path,
    *,
    base_name: str = "review_sheet",
    pdf: bool = False,
) -> dict[str, Path]:
    """同时渲染 9:16 与 16:9 两张审稿表。返回 {aspect: path}。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for aspect in (ASPECT_PORTRAIT, ASPECT_LANDSCAPE):
        p = render_review_sheet(
            manifest, d / f"{base_name}_{aspect.replace(':', 'x')}.png", aspect, pdf=pdf
        )
        paths[aspect] = p
    return paths
