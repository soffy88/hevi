"""Cover node: summary -> audience -> visual metaphor -> 9:16 / 3:4 / 16:9.

All covers are composed by hevi with PIL: the title/subtitle are real text
layers (not generated inside an image model), so the "generated image has no
text" rule from S24 stays true.  The illustration motif is simple geometry
driven by the chosen style category and theme colour.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.style_library import catalog

SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "3:4": (1080, 1440),
    "16:9": (1920, 1080),
}

_FONT_SERIF = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
_FONT_SANS = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
_FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

_AUDIENCE = (
    (("孩子", "儿童", "宝宝", "家长", "亲子", "睡前"), "家长与 3–10 岁孩子的共读场景"),
    (("学生", "考试", "学习", "记忆", "笔记", "考试"), "学生与自学者，想用更短时间弄懂"),
    (("职场", "工作", "汇报", "管理", "效率", "老板"), "职场人，关心怎么少踩坑、快决策"),
    (("创业", "品牌", "营销", "增长", "生意", "副业"), "创业者与小团队，关心成本和转化"),
    (("投资", "理财", "基金", "股票", "钱", "工资"), "普通投资者与上班族，关心自己的钱"),
    (("健康", "睡眠", "运动", "减肥", "医生", "身体"), "关注身体状态的普通读者"),
    (("AI", "ai", "模型", "科技", "数码", "工具"), "对新技术好奇、想马上上手的人"),
)
_DEFAULT_AUDIENCE = "对该主题好奇、希望在 1 分钟内抓住重点的普通观众"

_METAPHORS = (
    (("时间", "拖延", "效率", "截止"), "沙漏与跑道：时间从窄口漏下，人在跑道上被刻度追赶"),
    (("钱", "工资", "投资", "价格", "成本"), "漏斗与硬币：钱从宽口进入，经过层层缝隙后只剩一点"),
    (("记忆", "学习", "忘记", "复习"), "抽屉与便签：抽屉越满越难合上，常用那张便签被磨亮"),
    (("选择", "犹豫", "决策", "分岔"), "岔路与路牌：两条路在脚下分开，影子先走了一步"),
    (("关系", "沟通", "误解", "爱情"), "两座桥：桥面错开半米，说话的气泡在中间相遇"),
    (("焦虑", "压力", "情绪", "害怕"), "背上的石头：石头不大，但一直不放下就越来越重"),
    (("成长", "习惯", "坚持", "改变"), "年轮与台阶：一圈一圈长出来，台阶很小但方向一致"),
    (("科技", "AI", "机器", "算法"), "齿轮与手：齿轮自己转，手只在关键处拨一下"),
    (("自然", "环境", "动物", "植物"), "一片叶子的脉络：主干清楚，细脉连到每个角落"),
    (("信息", "谣言", "真相", "新闻"), "放大镜与回声：同一句话在房间里被放大成三种形状"),
)
_DEFAULT_METAPHOR = "一个被放大的日常物件：近看是细节，退后一步才看见结构"


def _text_of(source: Any) -> str:
    if isinstance(source, str):
        return source
    parts: list[str] = [
        str(source[key]) for key in ("title", "topic", "summary") if source.get(key)
    ]
    for shot in source.get("shots") or []:
        parts.extend(str(shot[key]) for key in ("big", "small", "narration", "text") if shot.get(key))
    for key in ("script", "transcript", "subtitles"):
        value = source.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("line") or ""))
                else:
                    parts.append(str(item))
    return "。".join(p for p in parts if p.strip())


def _sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[。！？!?；;\n])", text)
    return [s.strip(" 。；;\n\t") for s in raw if len(s.strip()) >= 6]


def summarize(source: Any, *, max_chars: int = 200) -> str:
    text = re.sub(r"\s+", " ", _text_of(source)).strip()
    sents = _sentences(text)
    if not sents:
        return text[:max_chars]
    # Extract lead + the sentence with the most concrete signal (numbers, 因果词).
    scored = []
    for i, s in enumerate(sents[:24]):
        score = 0.0
        score += 2.0 if i < 2 else 0
        score += 1.2 * len(re.findall(r"[0-9]+", s))
        score += 0.8 if any(w in s for w in ("因为", "所以", "其实", "但是", "不是", "而是")) else 0
        score += min(2.0, len(s) / 40)
        scored.append((score, i, s))
    picked = [sents[0]]
    for _, _, s in sorted(scored, reverse=True):
        if s not in picked:
            picked.append(s)
        if len("。".join(picked)) >= max_chars * 0.75:
            break
    out = ""
    for s in picked:
        cand = (out + "。" + s) if out else s
        if len(cand) > max_chars:
            break
        out = cand
    return out or text[:max_chars]


def audience_profile(source: Any) -> str:
    text = _text_of(source).lower()
    for keys, label in _AUDIENCE:
        if any(k.lower() in text for k in keys):
            return label
    return _DEFAULT_AUDIENCE


def visual_metaphor(source: Any) -> str:
    text = _text_of(source)
    for keys, metaphor in _METAPHORS:
        if any(k in text for k in keys):
            return metaphor
    return _DEFAULT_METAPHOR


def _title_candidates(summary: str, source: Any, limit: int = 3) -> list[str]:
    topic = ""
    if isinstance(source, dict):
        topic = str(source.get("title") or source.get("topic") or "")
    base = topic.strip() or _sentences(summary)[0] if _sentences(summary) else summary[:16]
    base = re.sub(r"[，。！？!?；;：:\s]+$", "", base)
    out = [base]
    if len(base) > 12:
        out.append(base[:12])
    # A second option: turn the first contrast into a question.
    for s in _sentences(summary):
        if any(w in s for w in ("为什么", "其实", "不是", "反而")):
            q = s.replace("。", "")
            out.append(q[:18])
            break
    seen = []
    for t in out:
        if t and t not in seen:
            seen.append(t)
    return seen[:limit]


def plan_cover(
    source: Any,
    *,
    style_id: str = "FA-039",
    theme_color_id: str = "C-27",
    layout_id: str = "SC-016",
    title: str = "",
) -> dict[str, Any]:
    summary = summarize(source)
    audience = audience_profile(source)
    metaphor = visual_metaphor(source)
    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    layout = catalog.get_layout(layout_id)
    titles = _title_candidates(summary, source)
    if title.strip():
        titles = [title.strip(), *[t for t in titles if t != title.strip()]]
    position = "center"
    if layout["category"].startswith("social"):
        lname = layout.get("name", "")
        position = "top" if "上" in lname else "bottom" if "下" in lname else "center"
    if layout["category"].startswith("infographic"):
        position = "top"
    return {
        "summary": summary,
        "audience": audience,
        "metaphor": metaphor,
        "titles": titles,
        "title": titles[0],
        "subtitle": summary[:40],
        "position": position,
        "style": catalog.style_brief(style),
        "theme_color": color,
        "layout": layout,
        "sizes": list(SIZES),
        "locked": {"style_id": style["id"], "theme_color_id": color["id"]},
        "prompts": {
            "zh": (
                f"风格名称：{style.get('generation_name','')}。主题色：{color.get('name_zh','')}。"
                f"主题：{metaphor}。画面只做视觉隐喻，不出现任何文字；文字由 HEVI 叠加。"
            ),
            "en": (
                f"Style: {style.get('generation_name','')}. Theme color: {color.get('name_en','')}. "
                f"Visual metaphor: {metaphor}. No text in the image; text is overlaid by HEVI."
            ),
        },
        "text_policy": "generated image contains no text; title/subtitle are PIL text layers",
        "attribution": catalog.ATTRIBUTION,
    }


def _font(path: str, size: int) -> Any:
    for cand in (path, _FONT_SANS, _FONT_BOLD):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        cand = current + ch
        if draw.textlength(cand, font=font) <= max_width:
            current = cand
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def _hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _draw_motif(
    draw: ImageDraw.ImageDraw,
    w: int,
    h: int,
    palette: dict[str, Any],
    style: dict[str, Any],
    *,
    cx: int | None = None,
    cy: int | None = None,
    r: int | None = None,
) -> None:
    accent = _hex_rgb(palette["accent"])
    ivory = _hex_rgb(palette["ivory"])
    cat = style.get("category", "FA")
    cx = w // 2 if cx is None else cx
    cy = int(h * 0.52) if cy is None else cy
    r = int(min(w, h) * 0.22) if r is None else r
    if cat in {"FB", "FD", "FE"}:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*accent, 70))
        draw.ellipse([cx - r // 2, cy - r // 2, cx + r // 4, cy + r // 4], fill=ivory)
        draw.arc([cx - r, cy - r, cx + r, cy + r], 200, 340, fill=ivory, width=max(3, w // 300))
    elif cat in {"FC", "FH"}:
        draw.rounded_rectangle([cx - r, cy - r, cx + r // 2, cy + r], radius=18, fill=accent)
        draw.ellipse([cx + r // 3, cy - r // 2, cx + r, cy + r // 3], fill=ivory)
    elif cat == "FI":
        draw.rectangle([cx - r, cy - r, cx + r, cy + r], fill=(*accent, 120))
        draw.polygon([(cx - r, cy + r), (cx - r // 3, cy), (cx + r // 6, cy + r // 2), (cx + r, cy - r // 4), (cx + r, cy + r)], fill=ivory)
    elif cat == "FF":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
        draw.ellipse([cx - r // 3, cy - r // 3, cx - r // 8, cy - r // 8], fill=ivory)
        draw.ellipse([cx + r // 8, cy - r // 3, cx + r // 3, cy - r // 8], fill=ivory)
    elif cat == "FG":
        draw.ellipse([cx - r, cy - r // 2, cx + r, cy + r // 2], fill=(*accent, 90))
        draw.ellipse([cx - r // 4, cy - r // 3, cx + r // 4, cy + r // 3], fill=ivory)
        draw.ellipse([cx - r // 10, cy - r // 8, cx + r // 6, cy + r // 5], fill=accent)
    else:
        # Editorial doodle: a loose continuous line + dot eyes.
        import random

        rng = random.Random(style.get("id", "x"))
        pts = []
        for i in range(9):
            ang = i / 8 * math.pi * 2
            pts.append((cx + math.cos(ang) * (r + rng.randint(-8, 8)), cy + math.sin(ang) * (r * 0.7 + rng.randint(-8, 8))))
        draw.line(pts, fill=ivory, width=max(4, w // 220), joint="curve")
        draw.ellipse([cx - r // 5, cy - r // 8, cx - r // 10, cy - r // 8 + r // 14], fill=ivory)
        draw.ellipse([cx + r // 10, cy - r // 8, cx + r // 5, cy - r // 8 + r // 14], fill=ivory)


def render_covers(
    plan: dict[str, Any],
    out_dir: str | Path,
    *,
    sizes: list[str] | None = None,
    basename: str = "cover",
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    palette = catalog.theme_palette(plan["theme_color"]["id"])
    if isinstance(plan.get("palette"), dict):
        palette.update(plan["palette"])
    style = catalog.get_style(plan["style"]["id"])
    outputs: dict[str, str] = {}
    checks: list[dict[str, Any]] = []
    for size in sizes or plan.get("sizes") or list(SIZES):
        w, h = SIZES[size]
        bg = _hex_rgb(palette["background"])
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img, "RGBA")
        # soft vertical gradient
        for y in range(h):
            t = y / max(1, h - 1)
            col = tuple(int(bg[i] * (1 - 0.18 * t) + _hex_rgb(palette["panel"])[i] * 0.18 * t) for i in range(3))
            draw.line([(0, y), (w, y)], fill=col)
        wide = w > h
        _draw_motif(
            draw, w, h, palette, style,
            cx=int(w * 0.76) if wide else None,
            cy=int(h * 0.60) if wide else None,
            r=int(h * 0.17) if wide else None,
        )
        # title text
        title_font = _font(_FONT_SERIF, max(54, int(w * (0.068 if wide else 0.085))))
        sub_font = _font(_FONT_SANS, max(28, int(w * (0.026 if wide else 0.034))))
        max_width = int(w * (0.52 if wide else 0.84))
        lines = _wrap(draw, plan["title"], title_font, max_width)[:3]
        line_h = int(title_font.size * 1.22)
        pos = plan.get("position", "center")
        if wide:
            y = int(h * 0.17)
        elif pos == "top":
            y = int(h * 0.12)
        elif pos == "bottom":
            y = int(h * 0.68)
        else:
            y = int(h * 0.20)
        ink = _hex_rgb(palette["ivory"])
        for line in lines:
            tw = draw.textlength(line, font=title_font)
            x = int(w * 0.06) if wide else (w - tw) / 2
            draw.text((x, y), line, font=title_font, fill=ink)
            y += line_h
        # subtitle
        sub = (plan.get("subtitle") or "")[:26]
        if sub:
            for line in _wrap(draw, sub, sub_font, max_width)[:2]:
                tw = draw.textlength(line, font=sub_font)
                x = int(w * 0.06) if wide else (w - tw) / 2
                draw.text((x, y + int(line_h * 0.35)), line, font=sub_font,
                          fill=_hex_rgb(palette["ivory_dim"]))
                y += int(sub_font.size * 1.5)
        # footer attribution (small, required by the licence)
        foot_font = _font(_FONT_SANS, max(18, int(w * 0.018)))
        foot = "风格库：yang0/handraw-style · HEVI 自绘预览"
        draw.text((int(w * 0.06), h - int(h * 0.05)), foot, font=foot_font,
                  fill=_hex_rgb(palette["past"]))
        name = f"{basename}-{size.replace(':','x')}.png"
        path = out / name
        img.save(path)
        outputs[size] = str(path)
        # readability checks
        contrast = (_luma(ink) + 0.05) / (_luma(bg) + 0.05)
        checks.append({
            "size": size,
            "path": str(path),
            "title": plan["title"],
            "title_lines": len(lines),
            "title_chars": len(plan["title"]),
            "overflow": bool(y > h - int(h * 0.10)),
            "contrast": round(contrast, 2),
            "text_layer": True,
            "ok": len(lines) <= 3 and y <= h - int(h * 0.10) and contrast >= 3.0,
        })
    manifest = {
        "plan": plan,
        "covers": outputs,
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
        "attribution": catalog.ATTRIBUTION,
        "text_policy": plan.get("text_policy"),
    }
    (out / "cover.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _luma(rgb: tuple[int, int, int]) -> float:
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255.0


__all__ = ["SIZES", "audience_profile", "plan_cover", "render_covers", "summarize", "visual_metaphor"]
