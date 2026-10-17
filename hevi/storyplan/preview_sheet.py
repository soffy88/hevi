"""漫画格分镜表渲染器 (storyboard.preview_sheet)。

根据 STORYBOOK_TASK.md 要求：
- 按镜头组生成一张漫画格分镜表（单张网格图）。
- 每格必须包含：
  1. 景别：【远景】/【中景】/【特写】（明确标签标识）
  2. 画面描述：镜头画面设定、动作与构图
  3. 台词：角色对白或旁白文本
- 视觉风格：铅笔线 + 淡彩手绘风格（Pencil sketch lines + light watercolor washes）。
- CPU 本地 PIL 渲染，100% 确定性，严禁 mock，严禁调用付费 API。
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hevi.kids.fonts import cjk_font
from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.model import StoryPlan


# 景别规范映射
SHOT_SCALE_MAP = {
    "establishing": "远景",
    "wide": "远景",
    "远景": "远景",
    "character": "中景",
    "medium": "中景",
    "中景": "中景",
    "insert": "特写",
    "close-up": "特写",
    "closeup": "特写",
    "cutaway": "特写",
    "特写": "特写",
}

# 淡彩配色方案 (Pencil + Light Watercolor Palette)
COLOR_PAPER_BG = (248, 245, 238)
COLOR_PANEL_BG = (255, 255, 252)
COLOR_INK_LINE = (38, 42, 48)
COLOR_PENCIL_SKETCH = (75, 80, 90)
COLOR_TEXT_PRIMARY = (32, 34, 38)
COLOR_TEXT_SECONDARY = (95, 100, 110)
COLOR_TEXT_MUTED = (140, 145, 155)

# 景别徽章淡彩色
BADGE_COLORS = {
    "远景": {"bg": (214, 232, 245), "text": (28, 70, 110), "border": (175, 205, 225)},
    "中景": {"bg": (255, 233, 218), "text": (130, 65, 25), "border": (235, 195, 175)},
    "特写": {"bg": (238, 228, 248), "text": (85, 40, 125), "border": (210, 190, 230)},
}

# 水彩渐变水晕预置
WASH_PALETTES = [
    [(225, 240, 225), (250, 245, 215), (215, 235, 245)],  # 森林晨光
    [(255, 235, 220), (255, 245, 210), (230, 245, 235)],  # 温暖友谊
    [(220, 230, 250), (235, 220, 245), (255, 240, 225)],  # 星空微光
    [(245, 230, 220), (235, 240, 230), (220, 235, 245)],  # 浅彩晨雾
]


def _normalize_shots(params: dict[str, Any], aspect: str) -> tuple[str, list[dict[str, Any]]]:
    """从 params 中提取规范化镜头列表。"""
    title = str(params.get("title") or "")
    normalized_shots: list[dict[str, Any]] = []

    # 1. 尝试从 shot_groups 解析
    raw_groups = params.get("shot_groups")
    if raw_groups and isinstance(raw_groups, list):
        for g_idx, group in enumerate(raw_groups):
            g_shots = group.get("shots", []) if isinstance(group, dict) else []
            for s_idx, s in enumerate(g_shots):
                scale = s.get("scale") or s.get("shot_type") or ("远景" if s_idx == 0 else "中景" if s_idx == 1 else "特写")
                normalized_shots.append({
                    "id": str(s.get("id") or s.get("shot_id") or f"G{g_idx+1}_S{s_idx+1}"),
                    "scale": SHOT_SCALE_MAP.get(str(scale).lower(), "中景"),
                    "description": str(s.get("prompt") or s.get("description") or s.get("action") or "晨光中的手绘场景"),
                    "dialogue": str(s.get("dialogue") or s.get("sound") or "一阵清脆的风铃声轻轻飘过..."),
                    "duration_s": float(s.get("duration_s", 4.0)),
                })

    # 2. 尝试从 shots 列表解析
    if not normalized_shots and "shots" in params and isinstance(params["shots"], list):
        for idx, s in enumerate(params["shots"]):
            scale = s.get("scale") or s.get("shot_type") or ("远景" if idx == 0 else "中景" if idx % 2 == 1 else "特写")
            normalized_shots.append({
                "id": str(s.get("id") or s.get("shot_id") or f"S{idx+1:02d}"),
                "scale": SHOT_SCALE_MAP.get(str(scale).lower(), "中景"),
                "description": str(s.get("prompt") or s.get("description") or s.get("action") or "手绘水彩场景"),
                "dialogue": str(s.get("dialogue") or s.get("sound") or "故事静静展开..."),
                "duration_s": float(s.get("duration_s", 4.0)),
            })

    # 3. 尝试从 plan 解析
    if not normalized_shots and "plan" in params and isinstance(params["plan"], dict):
        plan_obj = StoryPlan(**params["plan"])
        title = title or plan_obj.title
        all_shots = [sh for seq in plan_obj.shots.sequences for sc in seq.scenes for sh in sc.shots]
        for idx, sh in enumerate(all_shots):
            scale = sh.shot_type
            dur = (sh.end_ms - sh.start_ms) / 1000.0 if sh.end_ms > sh.start_ms else 4.0
            normalized_shots.append({
                "id": sh.shot_id,
                "scale": SHOT_SCALE_MAP.get(scale.lower(), "中景"),
                "description": f"{sh.purpose}: {sh.action}，最终{sh.end_state}",
                "dialogue": sh.sound,
                "duration_s": round(dur, 1),
            })

    # 4. 兜底自动生成故事计划
    if not normalized_shots:
        topic = str(params.get("topic") or "森林里的神秘种子")
        plan_obj = autofill_story_plan(topic, aspect=aspect)
        title = title or plan_obj.title
        all_shots = [sh for seq in plan_obj.shots.sequences for sc in seq.scenes for sh in sc.shots]
        for idx, sh in enumerate(all_shots):
            scale = sh.shot_type
            dur = (sh.end_ms - sh.start_ms) / 1000.0 if sh.end_ms > sh.start_ms else 4.0
            normalized_shots.append({
                "id": sh.shot_id,
                "scale": SHOT_SCALE_MAP.get(scale.lower(), "中景"),
                "description": f"{sh.purpose}。{sh.action}，{sh.end_state}",
                "dialogue": sh.sound,
                "duration_s": round(dur, 1),
            })

    title = title or "绘本故事分镜"
    return title, normalized_shots


def _draw_watercolor_illustration(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    scale: str,
    desc: str,
    shot_index: int,
) -> None:
    """在格内绘制具有铅笔线画与淡彩水晕质感的插画示意图。"""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0

    # 1. 淡彩水晕底色 (Soft Watercolor Wash Layer)
    wash_palette = WASH_PALETTES[shot_index % len(WASH_PALETTES)]
    mid_y = y0 + int(h * 0.55)

    # 渐变晕染天空与背景
    sky_color = wash_palette[0]
    draw.rectangle([(x0, y0), (x1, mid_y)], fill=sky_color)

    # 地面或近景淡彩
    ground_color = wash_palette[1]
    draw.rectangle([(x0, mid_y), (x1, y1)], fill=ground_color)

    # 有机水彩斑块 (Watercolor blobs)
    blob_color = wash_palette[2]
    cx = x0 + int(w * 0.5)
    cy = y0 + int(h * 0.45)
    r_w = int(w * 0.35)
    r_h = int(h * 0.28)
    draw.ellipse([(cx - r_w, cy - r_h), (cx + r_w, cy + r_h)], fill=blob_color)

    # 2. 铅笔线条构图 (Pencil Line Art Composition)
    # 根据景别绘制不同构图线
    if scale == "远景":
        # 地平线与远山/林冠轮廓
        pts_mountain = [
            (x0, mid_y + 10),
            (x0 + int(w * 0.25), mid_y - 25),
            (x0 + int(w * 0.55), mid_y - 10),
            (x0 + int(w * 0.8), mid_y - 30),
            (x1, mid_y + 5),
        ]
        draw.line(pts_mountain, fill=COLOR_PENCIL_SKETCH, width=2)
        # 远景树木轮廓笔触
        for tx in range(x0 + 40, x1 - 40, 50):
            th = 25 + (tx % 15)
            draw.line([(tx, mid_y), (tx, mid_y - th)], fill=COLOR_INK_LINE, width=2)
            draw.arc([(tx - 12, mid_y - th - 12), (tx + 12, mid_y - th + 12)], 0, 360, fill=COLOR_INK_LINE, width=1)
        # 飞鸟/云彩铅笔弧线
        draw.arc([(cx - 60, y0 + 30), (cx - 40, y0 + 45)], 200, 360, fill=COLOR_PENCIL_SKETCH, width=1)
        draw.arc([(cx - 40, y0 + 30), (cx - 20, y0 + 45)], 200, 360, fill=COLOR_PENCIL_SKETCH, width=1)

    elif scale == "特写":
        # 特写主体放大（如小种子/花瓣/角色面部眼神）
        draw.ellipse([(cx - 45, cy - 45), (cx + 45, cy + 45)], outline=COLOR_INK_LINE, width=3)
        # 细节排线 (Hatching lines)
        for offset in range(-30, 31, 8):
            draw.line([(cx + offset, cy - 25), (cx + offset + 10, cy + 25)], fill=COLOR_PENCIL_SKETCH, width=1)
        # 放射状微光/露珠线条
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            x_start = cx + int(55 * math.cos(rad))
            y_start = cy + int(55 * math.sin(rad))
            x_end = cx + int(72 * math.cos(rad))
            y_end = cy + int(72 * math.sin(rad))
            draw.line([(x_start, y_start), (x_end, y_end)], fill=COLOR_INK_LINE, width=2)

    else:  # 中景
        # 中景角色剪影与地面互动
        draw.line([(x0, mid_y + 20), (x1, mid_y + 20)], fill=COLOR_PENCIL_SKETCH, width=2)
        # 角色身体与耳朵铅笔弧线
        body_box = [(cx - 35, cy - 20), (cx + 35, cy + 50)]
        head_box = [(cx - 25, cy - 60), (cx + 25, cy - 15)]
        draw.ellipse(body_box, outline=COLOR_INK_LINE, width=2)
        draw.ellipse(head_box, outline=COLOR_INK_LINE, width=2)
        # 小耳朵/表情线条
        draw.line([(cx - 18, cy - 55), (cx - 28, cy - 75)], fill=COLOR_INK_LINE, width=2)
        draw.line([(cx - 28, cy - 75), (cx - 10, cy - 60)], fill=COLOR_INK_LINE, width=2)
        draw.line([(cx + 18, cy - 55), (cx + 28, cy - 75)], fill=COLOR_INK_LINE, width=2)
        draw.line([(cx + 28, cy - 75), (cx + 10, cy - 60)], fill=COLOR_INK_LINE, width=2)
        # 尾巴柔美弧线
        pts_tail = [(cx + 25, cy + 30), (cx + 65, cy + 15), (cx + 50, cy - 10)]
        draw.line(pts_tail, fill=COLOR_INK_LINE, width=2)

    # 3. 画面内景别与简要引导线装饰
    draw.rectangle([(x0, y0), (x1, y1)], outline=(200, 195, 185), width=1)


def _wrap_text(text: str, max_chars_per_line: int) -> list[str]:
    """中文按固定字数切行。"""
    text = (text or "").strip()
    if not text:
        return []
    lines = []
    while len(text) > max_chars_per_line:
        lines.append(text[:max_chars_per_line])
        text = text[max_chars_per_line:]
    if text:
        lines.append(text)
    return lines


def render_storyboard_preview_sheet(
    params: dict[str, Any],
    out_dir: Path,
    *,
    aspect: str = "16:9",
    seed: int = 42,
) -> Path:
    """渲染完整漫画格分镜表 PNG 并保存元数据 JSON。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    title, shots = _normalize_shots(params, aspect=aspect)
    if not shots:
        raise ValueError("Cannot render preview sheet: no shots available")

    # 1. 画布尺寸规划
    if aspect == "9:16":
        canvas_w, canvas_h = 1080, 1920
        cols = 2
    else:
        canvas_w, canvas_h = 1920, 1080
        cols = 3

    rows = math.ceil(len(shots) / cols)
    rows = max(1, rows)

    # 创建手绘纸质感画布
    img = Image.new("RGB", (canvas_w, canvas_h), color=COLOR_PAPER_BG)
    draw = ImageDraw.Draw(img)

    # 字体准备
    font_title = cjk_font(34)
    font_subtitle = cjk_font(18)
    font_badge = cjk_font(18)
    font_body = cjk_font(17)
    font_desc = cjk_font(15)
    font_meta = cjk_font(14)

    # 2. 绘制表头 (Header)
    header_h = 95
    draw.rectangle([(0, 0), (canvas_w, header_h)], fill=(255, 255, 255), outline=(225, 220, 210), width=1)
    draw.text((45, 20), f"动态绘本漫画格分镜表: 《{title}》", fill=COLOR_TEXT_PRIMARY, font=font_title)
    sub_info = f"风格: 铅笔线画 + 淡彩手绘水彩 | 景别规划: 远景/中景/特写交替 | 画布: {canvas_w}x{canvas_h} ({aspect}) | 镜头数: {len(shots)}"
    draw.text((48, 62), sub_info, fill=COLOR_TEXT_SECONDARY, font=font_subtitle)

    # 3. 计算漫画分格网格
    margin_x = 40
    margin_top = header_h + 30
    margin_bottom = 50
    gutter_x = 24
    gutter_y = 24

    avail_w = canvas_w - (margin_x * 2) - (gutter_x * (cols - 1))
    avail_h = canvas_h - margin_top - margin_bottom - (gutter_y * (rows - 1))

    cell_w = int(avail_w / cols)
    cell_h = int(avail_h / rows)

    # 4. 逐格绘制
    for idx, sh in enumerate(shots):
        r = idx // cols
        c = idx % cols
        if r >= rows:
            break

        x0 = margin_x + c * (cell_w + gutter_x)
        y0 = margin_top + r * (cell_h + gutter_y)
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        # 格子外框（带有漫画墨水线质感的粗线框）
        draw.rectangle([(x0, y0), (x1, y1)], fill=COLOR_PANEL_BG, outline=COLOR_INK_LINE, width=3)
        draw.rectangle([(x0 + 3, y0 + 3), (x1 - 3, y1 - 3)], outline=(225, 220, 210), width=1)

        # 4.1 格内布局切分
        # 上半部：插画区 (约 50%)；中半部：画面描述 (约 25%)；下半部：台词气泡框 (约 25%)
        card_pad = 12
        content_w = cell_w - (card_pad * 2)

        illu_h = int(cell_h * 0.46)
        illu_box = (x0 + card_pad, y0 + card_pad + 24, x1 - card_pad, y0 + card_pad + illu_h)

        # 绘制水彩插画示意图
        _draw_watercolor_illustration(draw, illu_box, sh["scale"], sh["description"], idx)

        # 4.2 顶部景别徽章与镜头号
        scale_name = sh["scale"]
        badge_style = BADGE_COLORS.get(scale_name, BADGE_COLORS["中景"])

        # 景别药丸徽章
        b_w, b_h = 76, 26
        bx0 = x0 + card_pad
        by0 = y0 + 8
        draw.rounded_rectangle([(bx0, by0), (bx0 + b_w, by0 + b_h)], radius=6, fill=badge_style["bg"], outline=badge_style["border"], width=1)
        draw.text((bx0 + 10, by0 + 3), f"【{scale_name}】", fill=badge_style["text"], font=font_badge)

        # 镜头号与时长
        dur_text = f"{sh['id']} | {sh['duration_s']}s"
        draw.text((x1 - card_pad - 85, by0 + 4), dur_text, fill=COLOR_TEXT_SECONDARY, font=font_meta)

        # 4.3 画面描述区域
        desc_y = illu_box[3] + 10
        draw.text((x0 + card_pad, desc_y), "【画面描述】", fill=COLOR_INK_LINE, font=font_meta)
        desc_lines = _wrap_text(sh["description"], max_chars_per_line=int(content_w / 14))
        cur_y = desc_y + 20
        for l in desc_lines[:2]:
            draw.text((x0 + card_pad, cur_y), l, fill=COLOR_TEXT_SECONDARY, font=font_desc)
            cur_y += 18

        # 4.4 台词 / 口播区域（气泡框设计）
        speech_box_y0 = y1 - int(cell_h * 0.22)
        speech_box_y1 = y1 - card_pad
        draw.rectangle([(x0 + card_pad, speech_box_y0), (x1 - card_pad, speech_box_y1)], fill=(255, 252, 240), outline=(230, 215, 185), width=1)
        draw.text((x0 + card_pad + 8, speech_box_y0 + 5), "💬 台词:", fill=(160, 90, 30), font=font_meta)
        dialogue_lines = _wrap_text(sh["dialogue"], max_chars_per_line=int((content_w - 70) / 15))
        d_text = dialogue_lines[0] if dialogue_lines else "..."
        if len(dialogue_lines) > 1:
            d_text = d_text + "..."
        draw.text((x0 + card_pad + 65, speech_box_y0 + 5), d_text, fill=COLOR_TEXT_PRIMARY, font=font_body)

    # 5. 底部页脚 (Footer)
    footer_text = f"Hevi Storyboard Generator • 铅笔淡彩漫画格 • SHA-256 确定性输出 • Total Shots: {len(shots)}"
    draw.text((margin_x, canvas_h - 32), footer_text, fill=COLOR_TEXT_MUTED, font=font_meta)

    png_path = out_dir / "storyboard_preview_sheet.png"
    img.save(png_path, format="PNG")

    # 保存元数据 JSON
    meta_path = out_dir / "preview_sheet_meta.json"
    meta_data = {
        "title": title,
        "aspect": aspect,
        "canvas_size": [canvas_w, canvas_h],
        "total_shots": len(shots),
        "columns": cols,
        "rows": rows,
        "shots": shots,
        "sha256": hashlib.sha256(png_path.read_bytes()).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return png_path


def render_preview_sheet_capability(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float = 0.0,
    aspect: str = "16:9",
    seed: int = 42,
) -> Any:
    """Capability 注册执行入口。"""
    from hevi.capabilities.registry import CapabilityResult

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    png_path = render_storyboard_preview_sheet(params, out_dir, aspect=aspect, seed=seed)
    meta_path = out_dir / "preview_sheet_meta.json"
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))

    return CapabilityResult(
        mp4=None,
        png=png_path,
        wav=None,
        duration_s=0.0,
        sha256=meta_data["sha256"],
        qa={
            "title": meta_data["title"],
            "total_shots": meta_data["total_shots"],
            "aspect": aspect,
            "canvas_size": meta_data["canvas_size"],
            "meta_path": str(meta_path),
            "sheet_path": str(png_path),
        },
    )
