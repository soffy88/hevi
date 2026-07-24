"""S13 引文呈现 + S12 对勘并置 —— 确定性纸雕镜头(零 provider,HEVI-EXPLAINER-PIPELINE-SPEC-001 §5)。

S13(N0-D-010 引文呈现分离):onscreen 引文走**竹简**(bamboo slips,右起竖排)或**字幕卡**纸雕,
  引文本体上屏、不占 VO 时长(时轴由同拍 vo 白话转述句驱动)。引文逐字取 quote.text(H2 已保真)。
S12(§5,清 G1a"数据有、画面无"欠账):**双半幅对折立起成双屏**,两半各呈一源之说,中缝对折,
  两说并陈不择一。文本取 DualAccountFact(数据已在,装配只呈现)。

复用 map_anim 纸雕图元(_paper_bg/_torn_rect/_deckle/_shadow_from/ease_out_back),同款做旧皮纸材质。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from hevi.tongjian.map_anim import _paper_bg, _shadow_from, _torn_rect, ease_out_back

FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
_BAMBOO = (196, 168, 108)  # 竹简色(做旧竹黄)
_INK = (38, 26, 14)


def _encode(frames_dir: Path, out_mp4: Path, fps: int) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(out_mp4),
        ],
        check=True,
    )
    return out_mp4


def _columns(text: str, per_col: int) -> list[str]:
    """竖排右起:文本按每列 per_col 字切列,返回列(右→左顺序渲染时列表顺序即右起)。"""
    clean = [c for c in text if c not in "，。、；：！？「」『』（）,.!?;:"]
    return ["".join(clean[i : i + per_col]) for i in range(0, len(clean), per_col)] or [""]


def render_quote_slip(
    quote_text: str,
    out_dir: Path,
    *,
    form: str = "竹简",
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 4.0,
    font_path: str = FONT,
) -> Path:
    """S13:onscreen 引文 → 竹简/字幕卡纸雕镜头(竖排右起,简牍逐条落定 ease_out_back)。

    竹简:每列一枚竹简(窄竖 _torn_rect + 上下编绳线),右起竖排逐字;简牍带 stagger 落下回弹。
    字幕卡:单张撕纸卡横排(form='字幕卡')。返回 mp4。引文逐字不改(H2 保真)。
    """
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_quote"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fnt = ImageFont.truetype(font_path, 40 if form == "竹简" else 34)

    if form == "字幕卡":
        return _render_card(quote_text, frames_dir, out_dir, w, h, n, fps, fnt)

    # ── 竹简竖排右起 ──
    per_col = max(6, min(12, (h - 220) // 48))
    cols = _columns(quote_text, per_col)
    ncol = len(cols)
    slip_w, gap = 56, 14
    total_w = ncol * slip_w + (ncol - 1) * gap
    x_right = (w + total_w) // 2 - slip_w  # 右起第一列 x
    top, bot = 110, h - 110
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = _paper_bg(w, h)
        slips = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(slips)
        for ci, col in enumerate(cols):  # ci=0 最右列(竖排右起)
            # 逐列 stagger 落下:右列先落
            lead = ci / max(1, ncol) * 0.35
            e = ease_out_back(max(0.0, min(1.0, (t - lead) / 0.5)))
            if e <= 0:
                continue
            x0 = x_right - ci * (slip_w + gap)
            drop = int((1 - e) * -260)  # 从上方落入
            y0, y1 = top + drop, bot + drop
            _torn_rect(sd, (x0, y0, x0 + slip_w, y1), _BAMBOO, seed=300 + ci * 7, amp=2.0)
            # 编绳(上下两道)
            for yy in (y0 + 26, y1 - 26):
                sd.line([(x0 + 4, yy), (x0 + slip_w - 4, yy)], fill=(90, 66, 34, 200), width=3)
            # 竖排文字(逐字,居中列内)
            if e > 0.85:
                ch_h = (y1 - y0 - 60) // max(1, per_col)
                for j, ch in enumerate(col):
                    bb = sd.textbbox((0, 0), ch, font=fnt)
                    cx = x0 + slip_w // 2 - (bb[2] - bb[0]) // 2
                    cy = y0 + 34 + j * ch_h
                    sd.text((cx + 1, cy + 1), ch, font=fnt, fill=(0, 0, 0, 120))
                    sd.text((cx, cy), ch, font=fnt, fill=(*_INK, 255))
        frame = Image.alpha_composite(frame, _shadow_from(slips, 5, 9, blur=7, alpha=90))
        frame = Image.alpha_composite(frame, slips)
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")
    return _encode(frames_dir, out_dir / "s13_quote_slip.mp4", fps)


def _render_card(text, frames_dir, out_dir, w, h, n, fps, fnt) -> Path:
    """字幕卡:单张撕纸卡,横排折行,整卡从下滑入回弹。"""
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= 16:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    lines = lines[:6]
    cw, ch_ = int(w * 0.62), 60 + len(lines) * 56
    cx0, cy0 = (w - cw) // 2, (h - ch_) // 2
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        e = ease_out_back(max(0.0, min(1.0, t / 0.5)))
        dy = int((1 - e) * 300)
        frame = _paper_bg(w, h)
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        _torn_rect(cd, (cx0, cy0 + dy, cx0 + cw, cy0 + ch_ + dy), (232, 220, 190), seed=71, amp=3.0)
        if e > 0.85:
            for i, ln in enumerate(lines):
                bb = cd.textbbox((0, 0), ln, font=fnt)
                x = (w - (bb[2] - bb[0])) // 2
                y = cy0 + 34 + dy + i * 56
                cd.text((x, y), ln, font=fnt, fill=(*_INK, 255))
        frame = Image.alpha_composite(frame, _shadow_from(card, 5, 9, blur=7, alpha=90))
        frame = Image.alpha_composite(frame, card)
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")
    return _encode(frames_dir, out_dir / "s13_quote_card.mp4", fps)


def render_dual_panel(
    dual,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 5.0,
    font_path: str = FONT,
) -> Path:
    """S12 对勘并置:单页沿中缝对折立起成**双半幅**,左右各呈一源之说(两说并陈不择一)。

    dual = DualAccountFact(accounts[2], dimension)。中缝对折用左右两半 x 位从中心张开模拟。
    """
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_dual"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fh = ImageFont.truetype(font_path, 30)
    fsrc = ImageFont.truetype(font_path, 26)
    fbody = ImageFont.truetype(font_path, 28)
    a0, a1 = dual.accounts[0], dual.accounts[1]
    panel_w, panel_h = int(w * 0.40), int(h * 0.60)
    cx, top, gap = w // 2, int(h * 0.24), 26

    def _wrap(s: str, per: int) -> list[str]:
        return [s[i : i + per] for i in range(0, len(s), per)] or [""]

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        # 对折张开:两半从中缝合拢态 → 各向外张到适度间隙落定(ease_out_back),两半全见。
        e = ease_out_back(max(0.0, min(1.0, (t - 0.05) / 0.55)))
        frame = _paper_bg(w, h)
        panels = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panels)
        for side, acc in ((-1, a0), (1, a1)):
            if side < 0:  # 左半:合拢态右边贴中缝 → 张开到 cx-gap-panel_w
                start, final = cx - panel_w, cx - gap - panel_w
            else:  # 右半:合拢态左边贴中缝 → 张开到 cx+gap
                start, final = cx, cx + gap
            px = int(start + e * (final - start))
            col = (232, 222, 196) if side < 0 else (222, 226, 214)
            _torn_rect(pd, (px, top, px + panel_w, top + panel_h), col, seed=440 + side, amp=3.0)
            if e > 0.9:
                pad = 22
                pd.text(
                    (px + pad, top + pad), acc.source_display, font=fsrc, fill=(120, 40, 30, 255)
                )
                yy = top + pad + 44
                for ln in _wrap(acc.summary, 11):
                    pd.text((px + pad, yy), ln, font=fbody, fill=(*_INK, 255))
                    yy += 40
        # 中缝对勘题头(两半张开后显现)
        if e > 0.9:
            head = f"史载互异 · {dual.dimension}"
            bb = pd.textbbox((0, 0), head, font=fh)
            hx = (w - (bb[2] - bb[0])) // 2
            pd.rectangle(
                [hx - 14, top - 52, hx + (bb[2] - bb[0]) + 14, top - 8],
                fill=(244, 236, 216, 220),
                outline=(90, 66, 40, 230),
            )
            pd.text((hx, top - 46), head, font=fh, fill=(62, 44, 26, 255))
        frame = Image.alpha_composite(frame, _shadow_from(panels, 5, 9, blur=7, alpha=85))
        frame = Image.alpha_composite(frame, panels)
        # 中缝线
        if e > 0.9:
            fd = ImageDraw.Draw(frame)
            fd.line([(cx, top - 4), (cx, top + panel_h + 4)], fill=(90, 66, 40, 120), width=2)
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")
    return _encode(frames_dir, out_dir / "s12_dual_panel.mp4", fps)
