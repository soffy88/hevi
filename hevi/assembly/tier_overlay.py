"""三档置信标注角标 —— 频道级视觉契约(LSXC-EP0-CHARTER-001 §3,2026-07-25 冻结)。

《我在历史现场》诚信内核:每镜右下角常驻一个三档标签,**跨集不变**。三色 + 形状冗余(色盲友好):

    实录  ◆ 实心  青蓝 #2E6DB4   史料直接支撑(可挂出处)
    推演  ◈ 半    琥珀 #C8862B   有依据的合理推断
    演绎  ◇ 空    紫灰 #7A6B8A   艺术加工

用法:
    render_tier_badge("实录", out.png, cite="史记·秦始皇本纪")  # 出透明 PNG 角标
    burn_tier_overlay(in.mp4, out.mp4, "演绎")                   # 整段右下角烧角标

这是**唯一**角标真源——所有集、所有镜都从这里出,不允许每集自画。位置/三色/图标/字号全锁死在
本模块,改这里=改频道视觉契约(需重新过目冻结)。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

# ── 频道视觉契约(冻结,勿散改)────────────────────────────────────────────────
_TIERS: dict[str, dict] = {
    "实录": {"rgb": (46, 109, 180), "glyph": "◆"},  # 青蓝,实心=史料实证
    "推演": {"rgb": (200, 134, 43), "glyph": "◈"},  # 琥珀,半=合理推断
    "演绎": {"rgb": (122, 107, 138), "glyph": "◇"},  # 紫灰,空=艺术加工
}
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
]
_MARGIN_FRAC = 0.028  # 角标距右/下边的边距(占视频高的比例)


def _font(size: int):
    from PIL import ImageFont

    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    import subprocess as _sp

    try:  # fc-match 兜底找任意 CJK 字体
        path = _sp.check_output(["fc-match", "-f", "%{file}", ":lang=zh"], text=True).strip()
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def render_tier_badge(tier: str, out_path: Path, *, cite: str | None = None, height: int = 56):
    """画一个三档角标 PNG(透明底,圆角胶囊:图标 + 二字标签;实录可挂出处细行)。返回 (w, h)。

    `height` = 标签胶囊高(px);出处行按比例小一号叠在胶囊下方。"""
    from PIL import Image, ImageDraw

    if tier not in _TIERS:
        raise ValueError(f"未知置信档:{tier!r}(只允许 {list(_TIERS)})")
    spec = _TIERS[tier]
    rgb = spec["rgb"]
    lab_f = _font(int(height * 0.5))
    cite_f = _font(int(height * 0.34))
    pad_x, pad_y = int(height * 0.34), int(height * 0.22)

    label = f"{spec['glyph']} {tier}"
    tmp = Image.new("RGBA", (4, 4))
    d0 = ImageDraw.Draw(tmp)
    lw = int(d0.textlength(label, font=lab_f))
    pill_w = lw + pad_x * 2
    pill_h = height
    cite_h = int(height * 0.52) if cite else 0
    cite_w = int(d0.textlength(cite, font=cite_f)) + pad_x * 2 if cite else 0
    W = max(pill_w, cite_w)
    H = pill_h + cite_h

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 胶囊(92% 不透明,右对齐)
    d.rounded_rectangle([W - pill_w, 0, W, pill_h], radius=int(pill_h * 0.28), fill=(*rgb, 235))
    d.text(
        (W - pill_w + pad_x, pad_y - int(height * 0.04)),
        label,
        font=lab_f,
        fill=(255, 255, 255, 255),
    )
    # 出处细行(实录):深色半透明衬底 + 白细字,右对齐贴胶囊下
    if cite:
        d.rounded_rectangle(
            [W - cite_w, pill_h + int(height * 0.06), W, H],
            radius=int(cite_h * 0.22),
            fill=(20, 24, 30, 190),
        )
        d.text(
            (W - cite_w + pad_x, pill_h + int(height * 0.1)),
            cite,
            font=cite_f,
            fill=(230, 235, 240, 255),
        )
    img.save(out_path)
    return img.size


def burn_tier_overlay(
    video_in: Path,
    video_out: Path,
    tier: str,
    *,
    cite: str | None = None,
    badge_height: int | None = None,
) -> Path:
    """整段视频右下角烧三档角标(位置/边距由本模块锁定)。返回成片路径。"""
    probe = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=height",
            "-of",
            "csv=p=0",
            str(video_in),
        ],
        text=True,
    ).strip()
    vh = int(probe or 1280)
    h = badge_height or max(36, int(vh * 0.044))
    margin = int(vh * _MARGIN_FRAC)
    with tempfile.TemporaryDirectory() as td:
        badge = Path(td) / "badge.png"
        render_tier_badge(tier, badge, cite=cite, height=h)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(video_in),
                "-i",
                str(badge),
                "-filter_complex",
                f"overlay=W-w-{margin}:H-h-{margin}",
                "-c:a",
                "copy",
                str(video_out),
            ],
            check=True,
        )
    return video_out
