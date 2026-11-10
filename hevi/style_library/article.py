"""Long-article illustration planning (2–5 image slots, one style + colour).

The plan picks the strongest sections, assigns a library layout to each slot,
renders a text-free motif card, and exports Markdown + inline WeChat HTML with
base64 images (same one-file delivery rule as S24).  Text lives in the HTML /
Markdown layer, never inside the generated image.
"""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hevi.style_library import catalog
from hevi.style_library.cover import _FONT_SANS, _draw_motif, _font, _hex_rgb

WIDTH, HEIGHT = 1080, 720

_STEP_WORDS = ("步骤", "第一", "第二", "第三", "首先", "然后", "最后", "流程", "方法")
_COMPARE_WORDS = ("对比", "区别", "vs", "VS", "而不是", "反而")
_DATA_WORDS = ("%", "％", "倍", "万", "亿", "数据", "增长", "下降")
_QUOTE_WORDS = ("“", "”", "「", "」", "说的", "一句话")


def _sections(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"heading": "", "body": []}
    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.*)$", line.strip())
        if m:
            if current["body"] or current["heading"]:
                sections.append(current)
            current = {"heading": m.group(2).strip(), "body": []}
        else:
            if line.strip():
                current["body"].append(line.strip())
    if current["body"] or current["heading"]:
        sections.append(current)
    if len(sections) <= 1:
        # No headings: group paragraphs into pseudo-sections.
        paras = [p for p in re.split(r"\n\s*\n", markdown) if p.strip()]
        sections = [{"heading": "", "body": [p]} for p in paras]
    return sections


def _score(section: dict[str, Any], index: int) -> float:
    body = " ".join(section.get("body") or [])
    score = 0.0
    score += 3.0 if index > 0 else 0.5
    score += 1.5 * len(re.findall(r"[0-9]+", body))
    score += 1.2 if any(w in body for w in _STEP_WORDS) else 0
    score += 1.0 if any(w in body for w in _COMPARE_WORDS) else 0
    score += 1.0 if any(w in body for w in _DATA_WORDS) else 0
    score += min(2.0, len(body) / 160)
    return score


def _pick_layout(section: dict[str, Any]) -> str:
    text = " ".join(section.get("body") or [])
    if any(w in text for w in _STEP_WORDS):
        return "IG-008"
    if any(w in text for w in _COMPARE_WORDS):
        return "IG-004"
    if any(w in text for w in _DATA_WORDS):
        return "IG-005"
    if any(w in text for w in _QUOTE_WORDS):
        return "SC-007"
    return "IG-003"


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plan_article(
    markdown: str,
    *,
    style_id: str = "FA-001",
    theme_color_id: str = "C-05",
    points: int = 3,
) -> dict[str, Any]:
    points = max(2, min(5, int(points)))
    sections = _sections(markdown)
    if not sections:
        raise ValueError("article is empty")
    ranked = sorted(
        ((_score(s, i), i, s) for i, s in enumerate(sections)),
        reverse=True,
    )
    chosen = sorted(ranked[:points], key=lambda row: row[1])
    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    slots = []
    for rank, (score, index, section) in enumerate(chosen, start=1):
        body = " ".join(section.get("body") or [])
        layout_id = _pick_layout(section)
        layout = catalog.get_layout(layout_id)
        slots.append({
            "slot": rank,
            "section_index": index,
            "heading": section.get("heading") or f"第 {rank} 段",
            "excerpt": _clip(body, 120),
            "caption": _clip(section.get("heading") or body, 28),
            "layout": {"id": layout["id"], "name": layout["name"], "category": layout["category"]},
            "prompt_zh": (
                f"图型：{layout['name']}。风格名称：{style.get('generation_name','')}。"
                f"主题色：{color.get('name_zh','')}。主题：{_clip(body, 80)}。画面不出现文字。"
            ),
            "prompt_en": (
                f"Layout: {layout.get('name_en') or layout['name']}. "
                f"Style: {style.get('generation_name','')}. Theme color: {color.get('name_en','')}. "
                f"Subject: {_clip(body, 80)}. No text in the image."
            ),
            "score": round(score, 2),
        })
    return {
        "style": catalog.style_brief(style),
        "theme_color": color,
        "theme_palette": catalog.theme_palette(color["id"]),
        "slots": slots,
        "locked": {"style_id": style["id"], "theme_color_id": color["id"]},
        "attribution": catalog.ATTRIBUTION,
    }


def _render_motif(path: Path, palette: dict[str, Any], style: dict[str, Any], slot: int) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), _hex_rgb(palette["background"]))
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(HEIGHT):
        t = y / HEIGHT
        bg = _hex_rgb(palette["background"])
        panel = _hex_rgb(palette["panel"])
        draw.line([(0, y), (WIDTH, y)], fill=tuple(int(bg[i] * (1 - 0.25 * t) + panel[i] * 0.25 * t) for i in range(3)))
    _draw_motif(draw, WIDTH, HEIGHT, palette, style)
    # small index mark, not article text
    font = _font(_FONT_SANS, 30)
    draw.text((WIDTH - 100, HEIGHT - 70), f"{slot:02d}", font=font, fill=_hex_rgb(palette["past"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def export_article(
    markdown: str,
    out_dir: str | Path,
    *,
    style_id: str = "FA-001",
    theme_color_id: str = "C-05",
    points: int = 3,
    title: str = "",
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = plan_article(markdown, style_id=style_id, theme_color_id=theme_color_id, points=points)
    palette = plan["theme_palette"]
    style = catalog.get_style(style_id)
    images: list[Path] = []
    for slot in plan["slots"]:
        path = out / f"illustration-{slot['slot']:02d}.png"
        _render_motif(path, palette, style, slot["slot"])
        slot["image"] = str(path)
        images.append(path)

    # Markdown: images are placed before the matching heading.
    lines = markdown.splitlines()
    by_heading = {s["heading"]: s for s in plan["slots"]}
    out_lines: list[str] = []
    used: set[str] = set()
    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.*)$", line.strip())
        if m and m.group(2).strip() in by_heading and m.group(2).strip() not in used:
            slot = by_heading[m.group(2).strip()]
            used.add(m.group(2).strip())
            out_lines.append(f"![{slot['caption']}]({Path(slot['image']).name})")
            out_lines.append("")
            out_lines.append(f"*图 {slot['slot']} · {slot['caption']}（版式 {slot['layout']['id']}）*")
            out_lines.append("")
        out_lines.append(line)
    md_path = out / "article-illustrated.md"
    md_path.write_text("\n".join(out_lines), encoding="utf-8")

    # WeChat HTML: inline styles + base64 images + copy button.
    parts: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.*)$", line.strip())
        if m:
            level = len(m.group(1))
            size = {1: 28, 2: 23, 3: 20}.get(level, 18)
            parts.append(
                f"<h{min(level,3)} style=\"margin:22px 0 10px;font-size:{size}px;"
                f"color:{palette['ivory']};font-family:'Noto Serif CJK SC',serif\">"
                f"{html.escape(m.group(2))}</h{min(level,3)}>"
            )
        elif line.strip():
            parts.append(
                f"<p style=\"margin:0 0 14px;font-size:16px;line-height:1.9;"
                f"color:{palette['ivory_dim']};font-family:'Noto Sans CJK SC',sans-serif\">"
                f"{html.escape(line.strip())}</p>"
            )
    # Put each image after the first paragraph following its heading.
    for slot in plan["slots"]:
        b64 = base64.b64encode(Path(slot["image"]).read_bytes()).decode("ascii")
        img = f"<img src='data:image/png;base64,{b64}' style='width:100%;border-radius:12px;display:block;margin:8px 0 4px' alt=''/>"
        caption = f"<p style='margin:0 0 18px;font-size:13px;color:{palette['past']}'>图 {slot['slot']} · {html.escape(slot['caption'])}</p>"
        # insert after the heading if present, else append.
        marker = f">{html.escape(slot['heading'])}</h"
        inserted = False
        for i, part in enumerate(parts):
            if marker in part:
                parts.insert(i + 1, img + caption)
                inserted = True
                break
        if not inserted:
            parts.append(img + caption)
    body = "".join(parts)
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + html.escape(title or "文章配图")
        + "</title></head><body style='margin:0;background:"
        + palette["background"]
        + ";padding:24px'>"
        "<div id='s27-article' style='max-width:720px;margin:0 auto'>"
        + f"<h1 style=\"margin:0 0 18px;font-size:30px;color:{palette['ivory']};font-family:'Noto Serif CJK SC',serif\">"
        + html.escape(title or "")
        + "</h1>"
        + body
        + "</div>"
        "<button onclick=\"(function(){var n=document.getElementById('s27-article');var r=document.createRange();r.selectNodeContents(n);var s=getSelection();s.removeAllRanges();s.addRange(r);document.execCommand('copy');this.textContent='已复制'})()\" style='position:fixed;right:20px;bottom:20px;padding:14px 22px;border:0;border-radius:999px;background:"
        + palette["accent"]
        + f";color:{palette['on_accent']};font-size:16px;cursor:pointer'>复制到公众号</button>"
        "</body></html>"
    )
    wechat_path = out / "article-wechat.html"
    wechat_path.write_text(doc, encoding="utf-8")
    manifest = {
        "plan": plan,
        "markdown": str(md_path),
        "wechat_html": str(wechat_path),
        "images": [str(p) for p in images],
        "text_policy": "images contain no text; headings/body are Markdown/HTML text layers",
        "attribution": catalog.ATTRIBUTION,
    }
    (out / "article-plan.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


__all__ = ["export_article", "plan_article"]
