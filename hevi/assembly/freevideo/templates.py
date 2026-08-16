"""freevideo:templates —— 程序化动画模板库(kind → 完整自包含 HTML)。

每个模板产出一个完整 <!doctype html> 文档,内联 CSS @keyframes + 少量 JS,
零外链资源(系统字体栈、纯色/SVG 图形)—— file:// 直接可跑,录屏即出动画。

动画纪律(来自 hevi RENDER-CONTRACT + html-video 模板经验):
  - 每个镜头一个可见动作节拍(One-Move Rule),开场动画 ≈2.2s 内完成,之后 hold;
  - 字符级/条目级入场错落有 delay,不用匀速直线(廉价 PPT 感);
  - 关键信息落定后静止 ≥1s(呼吸准则);
  - 无相机抖动/弹跳,除非模板明确(挤压标题的过冲是设计内元素)。

kind 列表(FRAME_KINDS):
  title      挤压大标题:逐字上浮过冲 + 光扫 + 副标
  typewriter 打字机:JS 逐字 + 光标闪烁 + 收尾光扫
  bar        数据条形图:网格绘制 → 条增长 → 数字滚动
  big_number 大数字 count-up + 轨道粒子
  cards      要点卡片:发牌式入场,满板静止 0.5s
  quote      金句:逐词揭示 + 双色 chromatic 像散
  timeline   时间轴:节点逐个点亮 + 进度线生长
  scene      程序化场景(复用 oprim_visual_scenes:火/头骨/洞穴/…)+ 前景文字
"""

from __future__ import annotations

import html
import re
from typing import Any

from hevi.pipeline_lite.oprim.oprim_visual_scenes import (
    VISUAL_CSS,
    build_visual_html,
    resolve_scene,
)

# ── 画布与配色 ────────────────────────────────────────────────────────────

FRAME_KINDS: tuple[str, ...] = (
    "title",
    "typewriter",
    "bar",
    "big_number",
    "cards",
    "quote",
    "timeline",
    "scene",
)

#: 默认配色(深底品牌感,hevi 蓝 + 警示红 + 金)。
_DEFAULT_PALETTE: dict[str, str] = {
    "bg0": "#0f1220",
    "bg1": "#171c33",
    "fg": "#f5f7ff",
    "muted": "#a8b0cf",
    "accent": "#38bdf8",
    "accent2": "#f43f5e",
    "accent3": "#fbbf24",
}

#: 浅底配色(纸面/简报风)。
_PAPER_PALETTE: dict[str, str] = {
    "bg0": "#faf7f0",
    "bg1": "#efe9dd",
    "fg": "#1c1a17",
    "muted": "#6f6a5e",
    "accent": "#c2410c",
    "accent2": "#0e7490",
    "accent3": "#a16207",
}

_PALETTES: dict[str, dict[str, str]] = {"deep": _DEFAULT_PALETTE, "paper": _PAPER_PALETTE}

#: 按 body 长度自动选模板的轮换表(首镜/末镜固定 title,中间循环)。
_AUTO_CYCLE: tuple[str, ...] = ("typewriter", "scene", "quote", "cards", "scene", "big_number")


# ── 公共装配器 ────────────────────────────────────────────────────────────


def _esc(value: Any) -> str:
    """转义文本(安全插入 HTML)。"""
    return html.escape(str(value))


def _reveal_tokens(text: str) -> list[str]:
    """中英混排逐字揭示 token:中文逐字(标点独立),英文按词(词后带空格)。

    中文无词边界,按空白切会整句一个 token —— 必须逐字。
    """
    tokens: list[str] = []
    for m in re.finditer(r"[A-Za-z0-9]+(?:['\u2019-][A-Za-z0-9]+)*|\s+|[^\s]", text):
        t = m.group(0)
        if t.isspace():
            continue  # 空白并入前一个 token 的尾随空间(由 HTML 折叠)
        if re.match(r"[A-Za-z0-9]", t):
            tokens.append(t + " ")
        else:
            tokens.append(t)
    return tokens or [text]


def _doc(css: str, body: str, *, title: str = "HEVI", broll: str | None = None) -> str:
    """拼装完整 HTML 文档。broll 给定时注入背景视频(真生成 B-roll 混排)。"""
    broll_html = ""
    if broll:
        broll_html = (
            '<div class="bgwrap"><video class="bg" src="'
            + broll
            + '" autoplay loop muted playsinline preload="auto"></video>'
            '<div class="bgshade"></div></div>'
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
{css}
</style>
</head>
<body>
{broll_html}
{body}
</body>
</html>
"""


def _base_css(
    w: int,
    h: int,
    pal: dict[str, str],
    *,
    extra: str = "",
    body_extra: str = "",
    has_broll: bool = False,
) -> str:
    """通用骨架 CSS:全屏舞台、入场淡入、安全区。

    extra 追加到 :root 之后; body_extra 追加到 body 规则之后。
    has_broll=True 时启用背景视频层(真生成 B-roll):深色遮罩保证前景可读。
    """
    broll_css = ""
    if has_broll:
        broll_css = """
.bgwrap { position: fixed; inset: 0; z-index: 0; overflow: hidden; }
.bg { width: 100%; height: 100%; object-fit: cover;
  filter: brightness(0.42) saturate(1.08);
  opacity: 0; animation: bgFade 0.7s ease 0.15s both; }
@keyframes bgFade { from { opacity: 0; } to { opacity: 1; } }
.bgshade { position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(10,12,22,.62) 0%, rgba(10,12,22,.30) 48%, rgba(10,12,22,.66) 100%); }
.stage { z-index: 1; }
"""
    return f"""
:root {{
  --w: {w}px; --h: {h}px;
  --bg0: {pal['bg0']}; --bg1: {pal['bg1']};
  --fg: {pal['fg']}; --muted: {pal['muted']};
  --accent: {pal['accent']}; --accent2: {pal['accent2']}; --accent3: {pal['accent3']};
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
  width: {w}px; height: {h}px; overflow: hidden;
  background:
    radial-gradient(120% 90% at 50% 0%, var(--bg1) 0%, var(--bg0) 62%);
  color: var(--fg);
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei",
    "Noto Sans SC", "Source Han Sans SC", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}}
{body_extra}
.stage {{
  width: {w}px; height: {h}px;
  position: relative; overflow: hidden;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 6% 7%;
}}
{broll_css}
/* 帧首 0.5s 从黑淡入(转场呼吸,避免硬切跳变) */
.stage > * {{ opacity: 0; animation: frameIn 0.5s ease 0.1s both; }}
@keyframes frameIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
.kicker {{
  color: var(--accent); font-size: 15px; font-weight: 700;
  letter-spacing: 0.32em; text-transform: uppercase; margin-bottom: 18px;
  animation: kickerIn 0.7s cubic-bezier(.2,.8,.2,1) 0.25s both !important;
}}
@keyframes kickerIn {{ from {{ opacity:0; transform: translateY(10px); }} to {{ opacity:1; transform:none; }} }}
{extra}
"""


def _sweep_css() -> str:
    """光扫(混色 screen 的渐变条横扫)。"""
    return """
.sweep { position: absolute; top: -10%; bottom: -10%; width: 22%;
  left: -30%; z-index: 5; pointer-events: none;
  background: linear-gradient(105deg, transparent 0%, rgba(255,255,255,.14) 46%,
    rgba(255,255,255,.34) 50%, rgba(255,255,255,.14) 54%, transparent 100%);
  transform: skewX(-14deg);
  animation: sweepX 1.1s cubic-bezier(.4,0,.2,1) 1.35s both;
}
@keyframes sweepX { from { left: -35%; } to { left: 115%; } }
"""


# ── 模板 1:title 挤压大标题 ───────────────────────────────────────────────


def _tpl_title(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    chars = list(title)
    char_spans = "".join(
        f'<span class="ch" style="animation-delay:{0.15 + i * 0.055:.2f}s">{_esc(c)}</span>'
        for i, c in enumerate(chars)
    )
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.ch {{ display:inline-block; opacity:0; transform: translateY(0.42em) scale(0.92);
  animation: chIn 0.6s cubic-bezier(.2,1.35,.3,1) both; }}
@keyframes chIn {{
  0% {{ opacity:0; transform: translateY(0.42em) scale(0.92); filter: blur(6px); }}
  60% {{ filter: blur(0); }}
  100% {{ opacity:1; transform:none; }}
}}
.title-line {{ font-size: {max(46, min(96, int(w * 0.085)))}px; font-weight: 800;
  letter-spacing: -0.02em; line-height: 1.15; text-align: center; max-width: 92%;
  text-shadow: 0 6px 40px rgba(56,189,248,.18); }}
.sub {{ margin-top: 26px; font-size: {max(20, min(34, int(w * 0.026)))}px; color: var(--muted);
  text-align: center; max-width: 78%; line-height: 1.7;
  animation: subIn 0.9s ease 0.95s both !important; }}
@keyframes subIn {{ from {{ opacity:0; transform: translateY(14px); }} to {{ opacity:1; transform:none; }} }}
.bar {{ margin-top: 34px; width: 64%; height: 3px; border-radius: 2px; opacity:.55;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  animation: barIn 0.8s ease 1.15s both !important; transform-origin: left; }}
@keyframes barIn {{ from {{ transform: scaleX(0); opacity:.9; }} to {{ transform:none; opacity:.55; }} }}
""",
    )
    body_html = f"""
<div class="stage">
  <div class="title-line">{char_spans}</div>
  <div class="sub">{_esc(body)}</div>
  <div class="bar"></div>
  <div class="sweep"></div>
</div>
"""
    return _doc(css, body_html, broll=broll,
    title=title[:40])


# ── 模板 2:typewriter 打字机 ──────────────────────────────────────────────


def _tpl_typewriter(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    text = body or title
    # 中文逐字/英文逐词(见 _reveal_tokens);JS 逐个点亮。
    tokens = _reveal_tokens(text)
    # JS 计时器不在 CSS 动画探测范围内 —— 间隔按帧时长自适应,保证在
    # 帧内打完 + 留 0.6s 收尾光扫(字数多时自动加速,不截断)。
    type_ms = max(30, min(120, int((dur - 1.4) * 1000 / max(len(tokens), 1))))
    spans = "".join(
        f'<span class="tw" data-i="{i}">{_esc(t)}</span>' for i, t in enumerate(tokens)
    )
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.typing {{ font-size: {max(26, min(52, int(w * 0.046)))}px; font-weight: 600;
  line-height: 1.85; text-align: left; max-width: 86%; white-space: pre-wrap;
  min-height: 3em; }}
.tw {{ opacity: 0.04; transition: opacity 0.18s ease; }}
.tw.on {{ opacity: 1; }}
.cursor {{ display:inline-block; width: 0.55em; height: 1.05em; margin-left: 2px;
  vertical-align: -0.18em; background: var(--accent); border-radius: 1px;
  animation: blink 1s steps(1) infinite; }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}
.sweep {{ animation-delay: 2.6s; }}
""",
    )
    body_html = f"""
<div class="stage">
  <div class="kicker">TYPEWRITER · {_esc(title[:24])}</div>
  <div class="typing">{spans}<span class="cursor" id="cur"></span></div>
  <div class="sweep"></div>
</div>
<script>
(function () {{
  var els = Array.prototype.slice.call(document.querySelectorAll('.tw'));
  var cur = document.getElementById('cur');
  var i = 0;
  var timer = setInterval(function () {{
    if (i >= els.length) {{
      clearInterval(timer);
      cur.style.display = 'none';
      var s = document.querySelector('.sweep');
      if (s) s.style.animation = 'sweepX 1.1s cubic-bezier(.4,0,.2,1) both';
      return;
    }}
    els[i].classList.add('on'); i += 1;
  }}, {type_ms});
}})();
</script>
"""
    return _doc(css, body_html, broll=broll,
    title=f"typewriter · {title[:24]}")


# ── 模板 3:bar 数据条形图 ────────────────────────────────────────────────


def _tpl_bar(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    items = _normalize_items(data, title=title, fallback=body)
    if not items:
        return _tpl_quote(title, body or title, data, w, h, pal, dur)
    max_v = max(i["value"] for i in items) or 1.0
    bar_css = ""
    for idx, it in enumerate(items):
        pct = max(8.0, it["value"] / max_v * 100)
        color = it.get("color") or (
            pal["accent"] if idx % 2 == 0 else pal["accent2"]
        )
        bar_css += f"""
.b{idx} {{ --bh: {pct:.1f}%; background: linear-gradient(180deg, {color}, {color}99);
  animation-delay: {0.5 + idx * 0.13:.2f}s; }}
"""
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.chart {{ width: 86%; height: {int(h * 0.5)}px; position: relative;
  display: flex; align-items: flex-end; gap: {max(10, int(w * 0.014))}px;
  padding: 0 6px; }}
.grid {{ position: absolute; inset: 0; display: flex; flex-direction: column;
  justify-content: space-between; pointer-events: none; }}
.grid i {{ border-top: 1px dashed rgba(168,176,207,.16); height: 0; }}
.col {{ flex: 1; height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: flex-end; gap: 8px; min-width: 0; }}
.bar {{
  width: 100%; max-width: 74px; height: 0; border-radius: 6px 6px 2px 2px;
  opacity: 0; transform-origin: bottom;
  animation: grow 0.9s cubic-bezier(.18,.9,.26,1) both;
  box-shadow: 0 8px 24px rgba(0,0,0,.35);
}}
@keyframes grow {{ 0% {{ height: 0; opacity: .9; }}
  100% {{ height: var(--bh, 8%); opacity: 1; }} }}
{bar_css}
.v {{ font-size: {max(18, min(30, int(w * 0.024)))}px; font-weight: 800;
  opacity: 0; animation: vIn 0.5s ease 1.1s both !important; }}
@keyframes vIn {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform:none; }} }}
.lbl {{ font-size: {max(13, min(20, int(w * 0.017)))}px; color: var(--muted);
  text-align: center; line-height: 1.4; opacity: 0;
  animation: lblIn 0.5s ease 0.6s both !important; }}
@keyframes lblIn {{ from {{ opacity: 0; transform: translateY(4px); }} to {{ opacity: 1; transform:none; }} }}
""",
    )
    cols = ""
    for idx, it in enumerate(items):
        cols += f"""
<div class="col">
  <div class="v" id="v{idx}" data-v="{it['value']}">0</div>
  <div class="bar b{idx}"></div>
  <div class="lbl">{_esc(it['label'])}</div>
</div>"""
    body_html = f"""
<div class="stage">
  <div class="kicker">DATA · {_esc(title[:24])}</div>
  <div class="chart">
    <div class="grid"><i></i><i></i><i></i><i></i></div>
    {cols}
  </div>
</div>
<script>
(function () {{
  var els = Array.prototype.slice.call(document.querySelectorAll('.v'));
  var started = false;
  function step() {{
    var done = true;
    els.forEach(function (el) {{
      var target = parseFloat(el.dataset.v);
      var cur = parseFloat(el.dataset.cur || '0');
      if (cur < target) {{
        var stepAmt = Math.max(target / 50, 0.01);
        var nxt = Math.min(target, cur + stepAmt);
        el.dataset.cur = nxt;
        el.textContent = Math.abs(nxt) >= 100
          ? Math.round(nxt).toLocaleString('en-US')
          : (Math.round(nxt * 10) / 10).toString();
        done = false;
      }}
    }});
    if (done) return;
    requestAnimationFrame(step);
  }}
  setTimeout(function () {{ if (!started) {{ started = true; step(); }} }}, 900);
}})();
</script>
"""
    return _doc(css, body_html, broll=broll,
    title=f"bar · {title[:24]}")


# ── 模板 4:big_number 大数字 ──────────────────────────────────────────────


def _tpl_big_number(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    num = _extract_number(data, body)
    unit = _unit_of(data)
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.num {{ font-size: {int(w * 0.2)}px; font-weight: 900; line-height: 1;
  letter-spacing: -0.03em; text-align: center;
  background: linear-gradient(180deg, #fff 0%, var(--accent) 120%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  filter: drop-shadow(0 10px 40px rgba(56,189,248,.28)); }}
.unit {{ font-size: {int(w * 0.05)}px; font-weight: 700; color: var(--accent);
  margin-left: 10px; }}
.numline {{ display: flex; align-items: baseline; justify-content: center; }}
.orbit {{ position: relative; width: {int(w * 0.5)}px; height: {int(w * 0.5)}px;
  margin: 34px auto 0; }}
.ring {{ position: absolute; inset: 0; border-radius: 50%; opacity: .5; }}
.r1 {{ border: 1px dashed var(--accent); animation: spin 14s linear infinite; }}
.r2 {{ inset: 9%; border: 1px solid rgba(244,63,94,.35);
  animation: spin 10s linear infinite reverse; }}
.dot {{ position: absolute; width: 10px; height: 10px; border-radius: 50%;
  background: var(--accent3); box-shadow: 0 0 14px var(--accent3); }}
.d1 {{ top: 4%; left: 46%; }} .d2 {{ bottom: 12%; right: 6%;
  background: var(--accent2); box-shadow: 0 0 14px var(--accent2); }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
""",
    )
    body_html = f"""
<div class="stage">
  <div class="kicker">{_esc(title[:32])}</div>
  <div class="numline">
    <div class="num" id="num" data-v="{num}">0</div>
    <div class="unit" id="unit">{_esc(unit)}</div>
  </div>
  <div class="sub" style="margin-top:26px;font-size:{max(18, int(w*0.022))}px;color:var(--muted);text-align:center;max-width:72%;line-height:1.7">{_esc(body)}</div>
  <div class="orbit">
    <div class="ring r1"><div class="dot d1"></div></div>
    <div class="ring r2"><div class="dot d2"></div></div>
  </div>
</div>
<script>
(function () {{
  var el = document.getElementById('num');
  var target = parseFloat(el.dataset.v);
  var t0 = null;
  function step(ts) {{
    if (t0 === null) t0 = ts;
    var p = Math.min(1, (ts - t0) / 1900);
    var e = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * e).toLocaleString('en-US');
    if (p < 1) requestAnimationFrame(step);
  }}
  requestAnimationFrame(step);
}})();
</script>
"""
    return _doc(css, body_html, broll=broll,
    title=f"big number · {title[:24]}")


# ── 模板 5:cards 要点卡片 ─────────────────────────────────────────────────


def _tpl_cards(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    items = _cards_from(data, body)
    cards = ""
    for idx, it in enumerate(items):
        cards += f"""
<div class="card" style="animation-delay:{0.35 + idx * 0.16:.2f}s">
  <span class="no">{idx + 1:02d}</span>
  <div class="ct">{_esc(it['title'])}</div>
  <div class="cs">{_esc(it['sub'])}</div>
</div>"""
    n = len(items)
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.grid {{ width: 100%; display: grid;
  grid-template-columns: repeat({2 if n >= 3 else n}, 1fr);
  gap: {max(12, int(w * 0.018))}px; max-width: 92%; }}
.card {{ position: relative; padding: 22px 20px; border-radius: 16px;
  background: rgba(255,255,255,.045);
  border: 1px solid rgba(168,176,207,.16);
  opacity: 0; transform: translateY(70px) rotate(2.5deg) scale(.96);
  animation: deal 0.55s cubic-bezier(.16,1,.3,1) both;
  box-shadow: 0 14px 34px rgba(0,0,0,.3); }}
.card:nth-child(even) {{ transform: translateY(70px) rotate(-2.5deg) scale(.96); }}
@keyframes deal {{
  0% {{ opacity: 0; transform: translateY(70px) rotate(2.5deg) scale(.96); }}
  100% {{ opacity: 1; transform: none; }}
}}
.no {{ position: absolute; top: 12px; right: 16px; font-size: 13px; font-weight: 800;
  color: var(--accent); opacity: .55; }}
.ct {{ font-size: {max(20, min(30, int(w * 0.026)))}px; font-weight: 700; line-height: 1.4; }}
.cs {{ margin-top: 10px; font-size: {max(13, min(18, int(w * 0.016)))}px;
  color: var(--muted); line-height: 1.6; }}
.dots {{ display: flex; gap: 8px; margin-top: 28px; }}
.dots i {{ width: 7px; height: 7px; border-radius: 50%; background: var(--muted);
  opacity: .3; animation: dotOn .4s ease both; }}
""",
    )
    dots = "".join(
        f'<i style="animation-delay:{1.0 + idx * 0.1:.2f}s"></i>' for idx in range(n)
    )
    body_html = f"""
<div class="stage">
  <div class="kicker">{_esc(title[:28])}</div>
  <div class="grid">{cards}</div>
  <div class="dots">{dots}</div>
</div>
"""
    return _doc(css, body_html, broll=broll,
    title=f"cards · {title[:24]}")


# ── 模板 6:quote 金句 ─────────────────────────────────────────────────────


def _tpl_quote(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    text = body or title
    words = _reveal_tokens(text)
    word_spans = "".join(
        f'<span class="w" style="animation-delay:{0.4 + i * 0.09:.2f}s">{_esc(t)}</span>'
        for i, t in enumerate(words)
    )
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.mark {{ font-size: {int(w * 0.12)}px; color: var(--accent2); font-family: Georgia, serif;
  height: 0.4em; line-height: 0.4; opacity: .9; align-self: flex-start;
  margin-left: 4%; animation: markIn 0.6s ease 0.2s both !important; }}
@keyframes markIn {{ from {{ opacity: 0; transform: scale(.6); }} to {{ opacity: .9; transform:none; }} }}
.qtext {{ font-size: {max(30, min(56, int(w * 0.05)))}px; font-weight: 700;
  line-height: 1.7; text-align: left; max-width: 88%; letter-spacing: .01em; }}
.w {{ display: inline-block; opacity: 0; transform: translateY(0.4em);
  filter: blur(8px);
  text-shadow: 2px 0 var(--accent2), -2px 0 var(--accent);
  animation: wIn 0.55s cubic-bezier(.2,.8,.2,1) both; }}
@keyframes wIn {{
  0% {{ opacity: 0; transform: translateY(0.4em); filter: blur(8px); }}
  70% {{ filter: blur(0); }}
  100% {{ opacity: 1; transform: none;
    text-shadow: 0 0 0 transparent; }}
}}
.src {{ margin-top: 30px; font-size: {max(15, min(22, int(w * 0.02)))}px;
  color: var(--muted); letter-spacing: .12em; align-self: flex-end;
  margin-right: 6%; animation: subIn 0.8s ease 1.4s both !important; }}
""",
    )
    body_html = f"""
<div class="stage">
  <div class="mark">“</div>
  <div class="qtext">{word_spans}</div>
  <div class="src">{_esc(title)}</div>
</div>
"""
    return _doc(css, body_html, broll=broll,
    title=f"quote · {title[:24]}")


# ── 模板 7:timeline 时间轴 ────────────────────────────────────────────────


def _tpl_timeline(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    items = _timeline_from(data, body)
    n = len(items)
    nodes = ""
    step = 100.0 / max(1, n - 1) if n > 1 else 50.0
    for idx, it in enumerate(items):
        left = 6 + idx * step * 0.88 if n > 1 else 50
        nodes += f"""
<div class="node" style="left:{left:.1f}%; animation-delay:{0.5 + idx * 0.28:.2f}s">
  <i class="dot"></i>
  <div class="nt">{_esc(it['title'])}</div>
  <div class="ns">{_esc(it['sub'])}</div>
</div>"""
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.axis {{ position: relative; width: 92%; height: {int(h * 0.34)}px; margin-top: 26px; }}
.rail {{ position: absolute; top: 6px; left: 2%; right: 2%; height: 3px;
  background: rgba(168,176,207,.14); border-radius: 2px; }}
.fill {{ position: absolute; top: 6px; left: 2%; height: 3px; width: 0%;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  animation: fillW {0.4 + n * 0.28:.2f}s ease {0.5:.1f}s both; }}
@keyframes fillW {{ from {{ width: 0; }} to {{ width: 96%; }} }}
.node {{ position: absolute; top: 0; width: 20%; text-align: center;
  opacity: 0; transform: translateY(10px);
  animation: nodeIn 0.5s cubic-bezier(.2,.8,.2,1) both; }}
@keyframes nodeIn {{ from {{ opacity: 0; transform: translateY(10px) scale(.8); }}
  to {{ opacity: 1; transform: none; }} }}
.dot {{ display: block; width: 13px; height: 13px; margin: 0 auto; border-radius: 50%;
  background: var(--bg0); border: 3px solid var(--accent);
  box-shadow: 0 0 0 0 rgba(56,189,248,.5);
  animation: ping 1.6s ease-out 0.6s both; }}
@keyframes ping {{ 0% {{ box-shadow: 0 0 0 0 rgba(56,189,248,.55); }}
  100% {{ box-shadow: 0 0 0 0 rgba(56,189,248,0); }} }}
.nt {{ margin-top: 12px; font-size: {max(14, min(20, int(w * 0.018)))}px; font-weight: 700; }}
.ns {{ margin-top: 4px; font-size: {max(11, min(15, int(w * 0.013)))}px;
  color: var(--muted); line-height: 1.5; }}
""",
    )
    body_html = f"""
<div class="stage">
  <div class="kicker">{_esc(title[:28])}</div>
  <div class="axis">
    <div class="rail"></div>
    <div class="fill"></div>
    {nodes}
  </div>
  <div class="sub" style="margin-top:22px;font-size:{max(15, int(w*0.018))}px;color:var(--muted);max-width:74%;text-align:center;line-height:1.6">{_esc(body)}</div>
</div>
"""
    return _doc(css, body_html, broll=broll,
    title=f"timeline · {title[:24]}")


# ── 模板 8:scene 程序化场景 ───────────────────────────────────────────────


def _tpl_scene(
    title: str, body: str, data: Any, w: int, h: int, pal: dict[str, str], dur: float,
    broll: str | None = None,
) -> str:
    scene = str(data.get("scene")) if isinstance(data, dict) and data.get("scene") else ""
    scene = scene or resolve_scene(0, {"title": title, "visual_query": body[:60]}, body)
    viz = build_visual_html(scene, title=title)
    css = _base_css(
        w,
        h,
        pal,
        has_broll=bool(broll),
        extra=f"""
.viz {{ position: relative; width: 92%; height: {int(h * 0.52)}px;
  border-radius: 22px; overflow: hidden;
  background: linear-gradient(160deg, #1a2238 0%, #0d111c 100%);
  box-shadow: 0 24px 60px rgba(0,0,0,.4), inset 0 0 0 1px rgba(125,211,252,.12);
  animation: vizIn 0.8s cubic-bezier(.2,.8,.2,1) 0.3s both !important; }}
@keyframes vizIn {{ from {{ opacity: 0; transform: scale(.94) translateY(16px); }}
  to {{ opacity: 1; transform: none; }} }}
.cap {{ margin-top: 24px; font-size: {max(20, min(32, int(w * 0.028)))}px;
  font-weight: 700; text-align: center; max-width: 88%; line-height: 1.5;
  animation: subIn 0.8s ease 0.9s both !important; }}
{VISUAL_CSS}
""",
    )
    body_html = f"""
<div class="stage">
  <div class="kicker">{_esc(title[:28])}</div>
  <div class="viz">{viz}</div>
  <div class="cap">{_esc(body)}</div>
</div>
"""
    return _doc(css, body_html, broll=broll,
    title=f"scene {scene} · {title[:20]}")


# ── 数据归一化助手 ────────────────────────────────────────────────────────


def _normalize_items(data: Any, *, title: str, fallback: str) -> list[dict[str, Any]]:
    """把 data 归一成 [{label, value, color?}]。支持 dict/列表/无 data 退化。"""
    if isinstance(data, dict):
        raw = data.get("items") or data.get("data") or data.get("bars")
    else:
        raw = data
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict):
                label = str(it.get("label") or it.get("name") or "")
                try:
                    value = float(it.get("value", it.get("v", 0)) or 0)
                except (TypeError, ValueError):
                    value = 0.0
                if label:
                    items.append({"label": label, "value": value, "color": it.get("color")})
            elif isinstance(it, (int, float)):
                items.append({"label": "", "value": float(it)})
    if not items:
        # 无结构化数据:把正文按逗号/分号/换行切成条目,值取条目标号。
        parts = [p.strip() for p in re.split(r"[，,；;。\n]", fallback) if p.strip()][:6]
        items = [
            {"label": p[:14], "value": (i + 1) * 10} for i, p in enumerate(parts)
        ] or [{"label": title[:14], "value": 10.0}]
    return items


def _extract_number(data: Any, fallback: str) -> float:
    if isinstance(data, dict):
        for key in ("number", "value", "num", "amount"):
            if key in data:
                try:
                    return float(data[key])
                except (TypeError, ValueError):
                    break
    if isinstance(data, (int, float)):
        return float(data)
    m = re.search(r"-?\d[\d,\.]*", fallback)
    if m:
        return float(m.group().replace(",", ""))
    return 100.0


def _unit_of(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("unit") or data.get("suffix") or "")
    return ""


def _cards_from(data: Any, fallback: str) -> list[dict[str, str]]:
    raw = data.get("cards") or data.get("items") if isinstance(data, dict) else data
    out: list[dict[str, str]] = []
    if isinstance(raw, list):
        out.extend(
            {
                "title": str(it.get("title") or it.get("label") or ""),
                "sub": str(it.get("sub") or it.get("desc") or ""),
            }
            for it in raw
            if isinstance(it, dict) and (it.get("title") or it.get("label"))
        )
    if not out:
        parts = [p.strip() for p in re.split(r"[，,；;。\n]", fallback) if p.strip()][:6]
        out = [{"title": p[:18], "sub": ""} for p in parts] or [
            {"title": fallback[:18], "sub": ""}
        ]
    return out


def _timeline_from(data: Any, fallback: str) -> list[dict[str, str]]:
    raw = data.get("items") or data.get("events") if isinstance(data, dict) else data
    out: list[dict[str, str]] = []
    if isinstance(raw, list):
        out.extend(
            {
                "title": str(it.get("title") or it.get("label") or ""),
                "sub": str(it.get("sub") or it.get("desc") or ""),
            }
            for it in raw
            if isinstance(it, dict)
        )
    if not out:
        parts = [p.strip() for p in re.split(r"[，,；;。\n]", fallback) if p.strip()][:5]
        out = [{"title": p[:12], "sub": ""} for p in parts]
    return out


# ── 统一入口 ──────────────────────────────────────────────────────────────


def render_frame_html(
    plan: Any,
    *,
    width: int = 1280,
    height: int = 720,
    palette: str = "deep",
    frame_duration: float = 4.0,
    broll: str | None = None,
) -> str:
    """一个 FramePlan → 完整自包含动画 HTML 文档。

    broll: 背景视频源(本地路径/相对名),注入铺满背景 + 深色遮罩。
    """
    pal = _PALETTES.get(palette, _DEFAULT_PALETTE)
    kind = plan.kind
    builder = {
        "title": _tpl_title,
        "typewriter": _tpl_typewriter,
        "bar": _tpl_bar,
        "big_number": _tpl_big_number,
        "cards": _tpl_cards,
        "quote": _tpl_quote,
        "timeline": _tpl_timeline,
        "scene": _tpl_scene,
    }.get(kind)
    if builder is None:
        kind = "quote"
        builder = _tpl_quote
    return builder(
        plan.title, plan.body, plan.data, width, height, pal, frame_duration, broll
    )


__all__ = ["FRAME_KINDS", "render_frame_html"]
