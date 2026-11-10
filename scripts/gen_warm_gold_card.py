"""生成暖黑金图解风格卡（JSON + 封面 + 妆面参考图）。

全部本地绘制：不下载图片、不调用外部服务。字体用系统 Noto（OFL）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hevi.explainer.warmgold import parts, style  # noqa: E402

ASSET = ROOT / "assets" / "style_cards"
FONT_SERIF = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
FONT_SANS = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _font(path: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _draw_part(
    img: Image.Image, part_id: str, box: tuple[int, int, int, int], t: float = 0.72
) -> None:
    x0, y0, x1, y1 = box
    payload = parts.draw(part_id, {"seed": 7}, t)
    W, H = x1 - x0, y1 - y0
    for it in payload["items"]:
        color = style.STYLE_CARD["palette"].get(str(it.get("f")), "#C8A96A")
        if color == "none":
            continue
        try:
            rgba = (*ImageColor.getrgb(color), int(255 * float(it.get("o", 1))))
        except ValueError:
            continue
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        kind = it["k"]
        if kind == "c":
            cx, cy, r = x0 + it["x"] * W, y0 + it["y"] * H, max(1, it["r"] * H)
            od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba)
        elif kind == "l":
            od.line(
                [x0 + it["x1"] * W, y0 + it["y1"] * H, x0 + it["x2"] * W, y0 + it["y2"] * H],
                fill=rgba,
                width=max(1, int(it.get("w", 1) * 2)),
            )
        elif kind == "r":
            od.rectangle(
                [
                    x0 + it["x"] * W,
                    y0 + it["y"] * H,
                    x0 + (it["x"] + it["w"]) * W,
                    y0 + (it["y"] + it["h"]) * H,
                ],
                fill=rgba,
            )
        elif kind == "p":
            pts = [(x0 + x * W, y0 + y * H) for x, y in it["pts"]]
            if len(pts) > 1:
                od.line(pts, fill=rgba, width=3)
        img.alpha_composite(overlay)


def build() -> tuple[Path, Path, Path]:
    ASSET.mkdir(parents=True, exist_ok=True)
    palette = style.STYLE_CARD["palette"]

    cover = Image.new("RGBA", (1280, 720), palette["background"])
    draw = ImageDraw.Draw(cover)
    draw.rectangle([0, 0, 1280, 720], fill=palette["background"])
    draw.line([(70, 88), (1210, 88)], fill=palette["gold"], width=1)
    draw.text((70, 112), "暖黑金图解", font=_font(FONT_SERIF, 78), fill=palette["ivory"])
    draw.text((74, 208), "WARM GOLD DIAGRAM", font=_font(FONT_SANS, 26), fill=palette["gold"])
    _draw_part(cover, "queue_lanes", (80, 300, 620, 660), 0.8)
    _draw_part(cover, "cum_jump", (680, 300, 1210, 660), 0.9)
    draw.text(
        (74, 646),
        "一句话 · 一个图形变化 · 一首音乐",
        font=_font(FONT_SANS, 24),
        fill=palette["ivory_dim"],
    )
    cover_path = ASSET / "warm_gold_cover.jpg"
    cover.convert("RGB").save(cover_path, quality=92)

    makeup = Image.new("RGBA", (720, 1280), palette["background"])
    draw = ImageDraw.Draw(makeup)
    draw.text((56, 96), "越着急", font=_font(FONT_SERIF, 96), fill=palette["ivory"])
    draw.text((56, 210), "越看不清", font=_font(FONT_SERIF, 96), fill=palette["ivory"])
    draw.text(
        (58, 356), "先别下结论，看它在动。", font=_font(FONT_SANS, 27), fill=palette["ivory_dim"]
    )
    _draw_part(makeup, "random_walk", (40, 470, 680, 980), 0.85)
    draw.text((58, 1110), "一次模拟", font=_font(FONT_SANS, 22), fill=palette["past"])
    draw.line([(56, 1152), (520, 1152)], fill=palette["gold"], width=1)
    draw.text((58, 1172), "暖黑金图解 · WARM GOLD", font=_font(FONT_SANS, 20), fill=palette["past"])
    makeup_path = ASSET / "warm_gold_makeup.jpg"
    makeup.convert("RGB").save(makeup_path, quality=92)

    card = style.style_card()
    card["cover"] = cover_path.name
    card["makeup"] = makeup_path.name
    card["parts_manifest"] = "warm_gold_parts.json"
    card_path = ASSET / "warm_gold.json"
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = parts.parts_manifest()
    (ASSET / "warm_gold_parts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "hevi" / "explainer" / "warmgold" / "parts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return card_path, cover_path, makeup_path


if __name__ == "__main__":
    card, cover, makeup = build()
    print(
        json.dumps(
            {"card": str(card), "cover": str(cover), "makeup": str(makeup)}, ensure_ascii=False
        )
    )
