"""Explainer Diagram — SVG 与 PIL 程序化关系图/流程图逐层展开渲染器。

纯 CPU、本地向量与光栅图生成，无需任何付费服务。
用于依据旁白节奏逐层展开流程图、概念图与要点卡片。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# 可用中文字体候选（按优先级回退）
_FONT_CANDIDATES = [
    "/home/soffy/.fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_p in _FONT_CANDIDATES:
        p = Path(font_p)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_flowchart_layer(
    nodes: Sequence[str],
    active_step: int,
    total_steps: int | None = None,
    *,
    width: int = 1280,
    height: int = 720,
    title: str = "工作原理解析",
    subtitle: str = "",
    out_path: Path | None = None,
) -> Path:
    """程序化绘制流程图逐层展开的当前帧。

    active_step: 1-indexed 当前展开到第几步 (1..N)。
    steps < active_step: 已展开/已完成；
    step == active_step: 当前正讲（发光高亮）；
    steps > active_step: 未展开（虚化或隐藏）。
    """
    total = total_steps or len(nodes)
    active = max(1, min(active_step, total))

    img = Image.new("RGBA", (width, height), (15, 23, 42, 255))  # 深色 Slate 背景
    draw = ImageDraw.Draw(img)

    title_font = _get_font(int(height * 0.055))
    sub_font = _get_font(int(height * 0.035))
    node_font = _get_font(int(height * 0.04))
    badge_font = _get_font(int(height * 0.028))

    # 1. 顶部标题
    title_y = int(height * 0.10)
    draw.text((int(width * 0.08), title_y), title, fill=(248, 250, 252, 255), font=title_font)
    if subtitle:
        draw.text(
            (int(width * 0.08), title_y + int(height * 0.07)),
            subtitle,
            fill=(148, 163, 184, 255),
            font=sub_font,
        )

    # 2. 节点布局计算 (横向排列)
    margin_x = int(width * 0.08)
    avail_w = width - margin_x * 2
    n_count = len(nodes)
    node_w = min(int(avail_w / max(n_count, 1) * 0.75), int(width * 0.28))
    node_h = int(height * 0.28)
    center_y = int(height * 0.52)
    top_y = center_y - node_h // 2

    step_gap = (avail_w - node_w * n_count) // max(n_count - 1, 1) if n_count > 1 else 0

    for idx, node_text in enumerate(nodes):
        step_num = idx + 1
        x1 = margin_x + idx * (node_w + step_gap)
        x2 = x1 + node_w
        y1 = top_y
        y2 = top_y + node_h

        if step_num > active:
            # 未展开步骤：浅浅虚线/极弱可见性轮廓
            draw.rounded_rectangle(
                [x1, y1, x2, y2],
                radius=16,
                fill=(30, 41, 59, 80),
                outline=(51, 65, 85, 120),
                width=2,
            )
            draw.text(
                (x1 + 20, y1 + 20),
                f"步骤 {step_num}",
                fill=(100, 116, 139, 120),
                font=badge_font,
            )
        elif step_num == active:
            # 当前聚焦步骤：高亮蓝绿辉光背景与醒目轮廓
            # 光晕
            glow_rect = [x1 - 6, y1 - 6, x2 + 6, y2 + 6]
            draw.rounded_rectangle(glow_rect, radius=20, fill=(14, 165, 233, 40))
            draw.rounded_rectangle(
                [x1, y1, x2, y2],
                radius=16,
                fill=(30, 58, 95, 255),
                outline=(56, 189, 248, 255),
                width=4,
            )
            # 步骤徽标
            draw.rounded_rectangle([x1 + 16, y1 + 16, x1 + 110, y1 + 52], radius=8, fill=(14, 165, 233, 255))
            draw.text((x1 + 26, y1 + 22), f"步骤 {step_num}", fill=(255, 255, 255, 255), font=badge_font)
            # 文本
            _draw_multiline_center(draw, node_text, x1, y1 + 55, node_w, node_h - 60, node_font, fill=(255, 255, 255, 255))
        else:
            # 已完成步骤：稳重墨青色、勾选标志
            draw.rounded_rectangle(
                [x1, y1, x2, y2],
                radius=16,
                fill=(30, 41, 59, 230),
                outline=(16, 185, 129, 220),
                width=2,
            )
            draw.rounded_rectangle([x1 + 16, y1 + 16, x1 + 110, y1 + 52], radius=8, fill=(16, 185, 129, 200))
            draw.text((x1 + 26, y1 + 22), f"✓ 步骤 {step_num}", fill=(255, 255, 255, 255), font=badge_font)
            _draw_multiline_center(draw, node_text, x1, y1 + 55, node_w, node_h - 60, node_font, fill=(226, 232, 240, 240))

        # 绘制步骤间连线箭头 (若当前箭头两端已展开)
        if idx < n_count - 1 and step_num < active:
            arrow_start_x = x2 + 10
            arrow_end_x = x2 + step_gap - 10
            arrow_y = center_y
            draw.line([(arrow_start_x, arrow_y), (arrow_end_x, arrow_y)], fill=(16, 185, 129, 240), width=4)
            # 箭头尖
            draw.polygon(
                [(arrow_end_x, arrow_y), (arrow_end_x - 12, arrow_y - 8), (arrow_end_x - 12, arrow_y + 8)],
                fill=(16, 185, 129, 240),
            )
        elif idx < n_count - 1 and step_num == active:
            # 当前到下一步之间的连线做呼吸中状态
            arrow_start_x = x2 + 10
            arrow_end_x = x2 + step_gap - 10
            arrow_y = center_y
            draw.line([(arrow_start_x, arrow_y), (arrow_end_x, arrow_y)], fill=(56, 189, 248, 160), width=3)
            draw.polygon(
                [(arrow_end_x, arrow_y), (arrow_end_x - 10, arrow_y - 6), (arrow_end_x - 10, arrow_y + 6)],
                fill=(56, 189, 248, 160),
            )

    target_path = out_path or Path(f"/tmp/flowchart_layer_{active}.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(target_path), format="PNG")
    return target_path


def render_image_card(
    title: str,
    key_terms: Sequence[str],
    summary: str = "",
    *,
    width: int = 1280,
    height: int = 720,
    out_path: Path | None = None,
) -> Path:
    """生成科技感概念信息卡片。"""
    img = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw = ImageDraw.Draw(img)

    title_font = _get_font(int(height * 0.06))
    term_font = _get_font(int(height * 0.045))
    body_font = _get_font(int(height * 0.038))

    # 大卡片底板
    card_rect = [int(width * 0.08), int(height * 0.12), int(width * 0.92), int(height * 0.88)]
    draw.rounded_rectangle(card_rect, radius=24, fill=(30, 41, 59, 240), outline=(56, 189, 248, 180), width=3)

    # 标题与装饰
    draw.text((int(width * 0.13), int(height * 0.18)), title, fill=(255, 255, 255, 255), font=title_font)
    draw.line(
        [(int(width * 0.13), int(height * 0.27)), (int(width * 0.87), int(height * 0.27))],
        fill=(71, 85, 105, 180),
        width=2,
    )

    # 核心关键词高亮气泡
    pill_x = int(width * 0.13)
    pill_y = int(height * 0.32)
    for term in key_terms[:4]:
        tw = int(len(term) * height * 0.045 + 36)
        th = int(height * 0.075)
        draw.rounded_rectangle([pill_x, pill_y, pill_x + tw, pill_y + th], radius=14, fill=(14, 165, 233, 220))
        draw.text((pill_x + 18, pill_y + 8), term, fill=(255, 255, 255, 255), font=term_font)
        pill_x += tw + 18

    # 详细摘要说明
    if summary:
        _draw_multiline_block(
            draw,
            summary,
            int(width * 0.13),
            int(height * 0.44),
            int(width * 0.74),
            int(height * 0.38),
            body_font,
            fill=(226, 232, 240, 240),
        )

    target_path = out_path or Path("/tmp/card_visual.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(target_path), format="PNG")
    return target_path


def render_presenter_frame(
    width: int = 1280,
    height: int = 720,
    *,
    name: str = "科普主讲人",
    topic: str = "",
    out_path: Path | None = None,
) -> Path:
    """生成全屏主讲人演播室视觉背景帧。"""
    img = Image.new("RGBA", (width, height), (11, 19, 43, 255))
    draw = ImageDraw.Draw(img)

    title_font = _get_font(int(height * 0.055))
    sub_font = _get_font(int(height * 0.035))

    # 舞台科技光效圆弧
    center_x = width // 2
    avatar_radius = int(height * 0.25)
    avatar_center_y = int(height * 0.48)

    # 主讲人形象轮廓圆形
    draw.ellipse(
        [
            center_x - avatar_radius,
            avatar_center_y - avatar_radius,
            center_x + avatar_radius,
            avatar_center_y + avatar_radius,
        ],
        fill=(30, 58, 95, 255),
        outline=(56, 189, 248, 255),
        width=4,
    )

    # 剪影图标
    draw.ellipse(
        [center_x - 60, avatar_center_y - 100, center_x + 60, avatar_center_y + 20],
        fill=(148, 163, 184, 255),
    )
    draw.pieslice(
        [center_x - 110, avatar_center_y - 10, center_x + 110, avatar_center_y + 170],
        start=180,
        end=360,
        fill=(148, 163, 184, 255),
    )

    # 底部标牌
    badge_rect = [center_x - 180, int(height * 0.78), center_x + 180, int(height * 0.88)]
    draw.rounded_rectangle(badge_rect, radius=12, fill=(15, 23, 42, 230), outline=(56, 189, 248, 200), width=2)
    draw.text((center_x - 90, int(height * 0.80)), name, fill=(255, 255, 255, 255), font=sub_font)

    if topic:
        draw.text((int(width * 0.06), int(height * 0.08)), topic, fill=(248, 250, 252, 255), font=title_font)

    target = out_path or Path("/tmp/presenter_full.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(target), format="PNG")
    return target


def _draw_multiline_center(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    w: int,
    h: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    chars_per_line = max(1, int(w / max(getattr(font, "size", 28), 28) * 1.5))
    lines: list[str] = []
    for i in range(0, len(text), chars_per_line):
        lines.append(text[i : i + chars_per_line])

    line_h = int(getattr(font, "size", 28) * 1.3)
    start_y = y + max(0, (h - len(lines) * line_h) // 2)

    for idx, ln in enumerate(lines[:3]):
        draw.text((x + 16, start_y + idx * line_h), ln, fill=fill, font=font)


def _draw_multiline_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    w: int,
    h: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    chars_per_line = max(1, int(w / max(getattr(font, "size", 24), 24) * 1.6))
    lines: list[str] = []
    for i in range(0, len(text), chars_per_line):
        lines.append(text[i : i + chars_per_line])

    line_h = int(getattr(font, "size", 24) * 1.4)
    for idx, ln in enumerate(lines[:6]):
        draw.text((x, y + idx * line_h), ln, fill=fill, font=font)
