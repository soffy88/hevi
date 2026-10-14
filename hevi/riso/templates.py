"""10 Information shape HTML/GSAP templates for RISO B-roll.

Clean-room self-developed templates implementing the RISO visual system:
- Solid paper background with fiber noise (no gradients).
- Ink A (deep key color) carrying structure and text.
- Ink B (fluorescent spot color) carrying exactly one climax highlight.
- mix-blend-mode: multiply for natural overprint.
- 3px misregistration on Ink B layer.
- Halftone dot texture for all shading and the bottom floor (1330-1920).
- Safe zones: 0-168 empty, text 168-1330, X>=940 free of text.
- Paused GSAP timeline driven by seek(t).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.riso.constants import (
    BOTTOM_SAFE_Y,
    BOTTOM_TEXT_Y,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    MISREGISTRATION_PX,
    PALETTES,
    RIGHT_CLEAR_X,
    TOP_SAFE_Y,
)


def _get_font_css(base_dir: Path | None = None) -> str:
    """Generate CSS @font-face rules pointing to subsetted local fonts."""
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent / "assets" / "fonts"
    fonts_dir_uri = base_dir.as_uri()

    return f"""
@font-face {{
  font-family: 'Source Han Serif SC';
  font-weight: 700;
  font-style: normal;
  src: url('{fonts_dir_uri}/SourceHanSerifSC-Bold.woff2') format('woff2');
  font-display: block;
}}
@font-face {{
  font-family: 'Source Han Sans SC';
  font-weight: 700;
  font-style: normal;
  src: url('{fonts_dir_uri}/SourceHanSansSC-Bold.woff2') format('woff2');
  font-display: block;
}}
@font-face {{
  font-family: 'Oswald';
  font-weight: 700;
  font-style: normal;
  src: url('{fonts_dir_uri}/Oswald-Bold.woff2') format('woff2');
  font-display: block;
}}
@font-face {{
  font-family: 'Oswald';
  font-weight: 400;
  font-style: normal;
  src: url('{fonts_dir_uri}/Oswald-Regular.woff2') format('woff2');
  font-display: block;
}}
@font-face {{
  font-family: 'JetBrains Mono';
  font-weight: 700;
  font-style: normal;
  src: url('{fonts_dir_uri}/JetBrainsMono-Bold.woff2') format('woff2');
  font-display: block;
}}
@font-face {{
  font-family: 'JetBrains Mono';
  font-weight: 400;
  font-style: normal;
  src: url('{fonts_dir_uri}/JetBrainsMono-Regular.woff2') format('woff2');
  font-display: block;
}}
"""


def _get_vendor_gsap_uri() -> str:
    vendor_path = Path(__file__).resolve().parent / "assets" / "vendor" / "gsap.min.js"
    return vendor_path.as_uri()


def render_template_html(
    template_name: str,
    data: dict[str, Any],
    palette_key: str = "ink_blue_neon_pink",
    seed: int = 42,
    fonts_dir: Path | None = None,
) -> str:
    """Generate the full standalone HTML for any of the 10 RISO templates."""
    palette = PALETTES.get(palette_key, PALETTES["ink_blue_neon_pink"])
    font_css = _get_font_css(fonts_dir)
    gsap_uri = _get_vendor_gsap_uri()

    # Shared HTML header and SVG defs
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1080, height=1920, initial-scale=1.0">
<title>RISO - {template_name}</title>
<style>
{font_css}

* {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}

body {{
  width: 1080px;
  height: 1920px;
  overflow: hidden;
  background-color: {palette.paper};
  position: relative;
  font-family: 'Source Han Sans SC', sans-serif;
  -webkit-font-smoothing: antialiased;
}}

/* Top safe zone 0-168 is kept completely clear */
.safe-zone-top {{
  position: absolute;
  top: 0;
  left: 0;
  width: 1080px;
  height: 168px;
  pointer-events: none;
}}

/* Content zone strictly 168-1330, width <= 940 */
.content-stage {{
  position: absolute;
  top: 168px;
  left: 80px;
  width: 860px;
  height: 1162px;
  max-width: 860px;
  max-height: 1162px;
}}

/* Ink Layers with Overprint Multiply */
.ink-layer {{
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}}

.ink-a {{
  color: {palette.ink_a};
  fill: {palette.ink_a};
  stroke: {palette.ink_a};
  mix-blend-mode: multiply;
  z-index: 10;
}}

.ink-b {{
  color: {palette.ink_b};
  fill: {palette.ink_b};
  stroke: {palette.ink_b};
  mix-blend-mode: multiply;
  /* 3px riso misregistration */
  transform: translate({MISREGISTRATION_PX}px, 2px);
  z-index: 20;
}}

/* SVG Noise Paper Texture */
.paper-noise {{
  position: absolute;
  top: 0;
  left: 0;
  width: 1080px;
  height: 1920px;
  pointer-events: none;
  opacity: 0.18;
  mix-blend-mode: multiply;
  z-index: 5;
}}

/* Bottom decorative floor: 1330 - 1920 */
.riso-floor {{
  position: absolute;
  top: 1330px;
  left: 0;
  width: 1080px;
  height: 590px;
  pointer-events: none;
  z-index: 15;
}}

/* Common typography */
.font-serif {{ font-family: 'Source Han Serif SC', serif; }}
.font-sans {{ font-family: 'Source Han Sans SC', sans-serif; }}
.font-num {{ font-family: 'Oswald', sans-serif; }}
.font-mono {{ font-family: 'JetBrains Mono', monospace; }}

</style>
<script src="{gsap_uri}"></script>
</head>
<body>

<!-- SVG Paper Noise & Halftone Definitions -->
<svg class="paper-noise" width="1080" height="1920" xmlns="http://www.w3.org/2000/svg">
  <filter id="fiber-noise">
    <feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" seed="{seed}" result="noise" />
    <feColorMatrix type="matrix" values="0 0 0 0 0.1   0 0 0 0 0.1   0 0 0 0 0.1   0 0 0 0.25 0" />
  </filter>
  <rect width="1080" height="1920" filter="url(#fiber-noise)" fill="none" />
</svg>

<!-- Bottom Halftone Texture Floor (1330 - 1920) -->
<div class="riso-floor">
  <svg width="1080" height="590" viewBox="0 0 1080 590" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <pattern id="halftone-pattern" width="16" height="16" patternUnits="userSpaceOnUse">
        <circle cx="8" cy="8" r="2.2" fill="{palette.ink_a}" opacity="0.35" />
      </pattern>
      <pattern id="halftone-accent" width="16" height="16" patternUnits="userSpaceOnUse">
        <circle cx="8" cy="8" r="3.0" fill="{palette.ink_b}" opacity="0.5" />
      </pattern>
    </defs>
    <!-- Halftone bed layer -->
    <rect x="80" y="40" width="860" height="480" fill="url(#halftone-pattern)" />
    <!-- Ink B accent bar on floor -->
    <rect x="80" y="20" width="180" height="8" fill="{palette.ink_b}" />
    <line x1="80" y1="24" x2="940" y2="24" stroke="{palette.ink_a}" stroke-width="2" stroke-dasharray="6,6" opacity="0.6" />
    
    <!-- Riso registration crosshairs and plate annotations -->
    <g transform="translate(80, 530)">
      <circle cx="0" cy="0" r="10" stroke="{palette.ink_a}" stroke-width="1.5" fill="none" />
      <line x1="-14" y1="0" x2="14" y2="0" stroke="{palette.ink_a}" stroke-width="1.5" />
      <line x1="0" y1="-14" x2="0" y2="14" stroke="{palette.ink_a}" stroke-width="1.5" />
      <text x="24" y="4" font-family="'JetBrains Mono'" font-size="14" fill="{palette.ink_a}" opacity="0.7">RISO 2-COLOR SEPARATION // 600 DPI // PLATE A+B</text>
    </g>
    <g transform="translate(937, 530)">
      <circle cx="3" cy="2" r="10" stroke="{palette.ink_b}" stroke-width="1.5" fill="none" />
      <line x1="-11" y1="2" x2="17" y2="2" stroke="{palette.ink_b}" stroke-width="1.5" />
      <line x1="3" y1="-12" x2="3" y2="16" stroke="{palette.ink_b}" stroke-width="1.5" />
    </g>
  </svg>
</div>

<!-- Template Stage -->
<div class="content-stage">
{_render_template_body(template_name, data, palette)}
</div>

<script>
// TOP DATA OBJECT (all variations driven strictly through DATA)
const DATA = {json.dumps(data, ensure_ascii=False, indent=2)};

// Font load validation gate: silent fallback is strictly forbidden!
window.__fontsReady = false;
window.__fontError = null;

async function checkFontsLoaded() {{
  try {{
    await Promise.all([
      document.fonts.load('700 24px "Source Han Serif SC"', '测试文字'),
      document.fonts.load('700 24px "Source Han Sans SC"', '测试文字'),
      document.fonts.load('700 24px "Oswald"', '0123456789'),
      document.fonts.load('400 24px "Oswald"', '0123456789'),
      document.fonts.load('700 24px "JetBrains Mono"', '0123456789'),
      document.fonts.load('400 24px "JetBrains Mono"', '0123456789')
    ]);
    await document.fonts.ready;
    const required = [
      {{ name: 'Source Han Serif SC', sample: '测试' }},
      {{ name: 'Source Han Sans SC', sample: '测试' }},
      {{ name: 'Oswald', sample: '0123' }},
      {{ name: 'JetBrains Mono', sample: '0123' }}
    ];
    for (const f of required) {{
      if (!document.fonts.check(`24px "${{f.name}}"`, f.sample)) {{
        throw new Error(`Required font '${{f.name}}' failed to load! Silent fallback forbidden.`);
      }}
    }}
    window.__fontsReady = true;
  }} catch (err) {{
    window.__fontError = err.message || String(err);
    console.error("Font load failure:", window.__fontError);
  }}
}}
checkFontsLoaded();

// Paused GSAP timeline driven by seek(t)
window.tl = gsap.timeline({{ paused: true }});

{_render_template_animation(template_name)}

window.__renderFrame = function(timeSeconds) {{
  window.tl.seek(timeSeconds);
}};
</script>
</body>
</html>
"""
    return html


def _render_template_body(template_name: str, data: dict[str, Any], palette: Any) -> str:
    """Render inner content stage for the specific template."""
    if template_name == "versus":
        myth = data.get("myth", "")
        reality = data.get("reality", "")
        tag = data.get("tag", "误区翻转")
        return f"""
  <!-- Ink A Structure -->
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 30px;">
      <span class="font-mono" style="font-size: 20px; font-weight: 700; border: 2px solid {palette.ink_a}; padding: 4px 12px; letter-spacing: 2px;">{tag}</span>
      <span class="font-mono" style="font-size: 16px; opacity: 0.6;">01 // MYTH vs TRUTH</span>
    </div>
    
    <!-- Top Box: Myth (Ink A) -->
    <div id="myth-box" style="border: 3px solid {palette.ink_a}; padding: 40px; margin-bottom: 50px; position: relative;">
      <div class="font-mono" style="font-size: 18px; margin-bottom: 16px; opacity: 0.7;">COMMON BELIEF // 误区</div>
      <div class="font-serif" style="font-size: 52px; line-height: 1.35; font-weight: 700;">{myth}</div>
      <!-- Strikethrough ink line -->
      <div id="strike-line" style="position: absolute; top: 58%; left: 30px; width: 0%; height: 6px; background-color: {palette.ink_a};"></div>
    </div>
  </div>

  <!-- Ink B Climax Highlight -->
  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Bottom Box: Reality (Ink B) -->
    <div id="reality-box" style="margin-top: 400px; background-color: {palette.ink_b}; color: {palette.paper}; padding: 46px 40px; position: relative; opacity: 0; transform: translateY(30px);">
      <div class="font-mono" style="font-size: 18px; margin-bottom: 16px; color: {palette.paper}; opacity: 0.9; letter-spacing: 1px;">REALITY // 真相</div>
      <div class="font-sans" style="font-size: 54px; line-height: 1.35; font-weight: 700; color: {palette.paper};">{reality}</div>
    </div>
  </div>
"""

    elif template_name == "title":
        title = data.get("title", "")
        subtitle = data.get("subtitle", "")
        number = data.get("number", "01")
        tag = data.get("tag", "核心章节")
        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid {palette.ink_a}; padding-bottom: 24px; margin-bottom: 50px;">
      <span class="font-mono" style="font-size: 22px; font-weight: 700; letter-spacing: 2px;">{tag}</span>
      <span class="font-mono" style="font-size: 18px; opacity: 0.6;">SECTION BREAK</span>
    </div>

    <!-- Big Number in Ink A -->
    <div id="title-num" class="font-num" style="font-size: 160px; line-height: 0.9; margin-bottom: 40px; opacity: 0; transform: translateY(-40px);">{number}</div>

    <!-- Title in Serif -->
    <div id="title-main" class="font-serif" style="font-size: 64px; line-height: 1.35; font-weight: 700; margin-bottom: 60px; opacity: 0;">
      {title}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Subtitle card in Ink B -->
    <div id="title-sub" style="margin-top: 600px; border-left: 10px solid {palette.ink_b}; padding: 24px 30px; opacity: 0; transform: translateX(30px);">
      <div class="font-sans" style="font-size: 44px; line-height: 1.4; font-weight: 700; color: {palette.ink_b};">{subtitle}</div>
    </div>
  </div>
"""

    elif template_name == "number":
        context = data.get("context", "")
        number = data.get("number", "0")
        unit = data.get("unit", "")
        insight = data.get("insight", "")
        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div class="font-mono" style="font-size: 20px; font-weight: 700; letter-spacing: 2px; border-bottom: 2px solid {palette.ink_a}; padding-bottom: 16px; margin-bottom: 60px;">
      METRIC // {context}
    </div>

    <!-- Insight below number -->
    <div id="num-insight" style="margin-top: 520px; border-top: 2px dashed {palette.ink_a}; padding-top: 36px; opacity: 0;">
      <div class="font-sans" style="font-size: 46px; line-height: 1.45; font-weight: 700;">{insight}</div>
    </div>
  </div>

  <!-- Ink B Giant Number -->
  <div class="ink-layer ink-b" id="stage-ink-b">
    <div id="num-giant" style="margin-top: 100px; display: flex; align-items: baseline; opacity: 0; transform: scale(0.85);">
      <span class="font-num" style="font-size: 220px; font-weight: 700; line-height: 0.9; color: {palette.ink_b};">{number}</span>
      <span class="font-serif" style="font-size: 64px; font-weight: 700; margin-left: 16px; color: {palette.ink_b};">{unit}</span>
    </div>
  </div>
"""

    elif template_name == "compare":
        # Bar length strictly proportional to values
        val_a = float(data.get("val_a", 10))
        val_b = float(data.get("val_b", 26))
        label_a = data.get("label_a", "前期")
        label_b = data.get("label_b", "后期")
        caption = data.get("caption", "")
        max_val = max(val_a, val_b, 1.0)
        pct_a = int((val_a / max_val) * 100)
        pct_b = int((val_b / max_val) * 100)

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div class="font-mono" style="font-size: 20px; font-weight: 700; letter-spacing: 2px; margin-bottom: 40px;">
      PROPORTIONAL COMPARISON // 对比
    </div>

    <!-- Bar A (Muted Ink A) -->
    <div style="margin-bottom: 60px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 16px;">
        <span class="font-sans" style="font-size: 36px; font-weight: 700;">{label_a}</span>
        <span class="font-num" style="font-size: 44px; font-weight: 700;">{data.get('disp_a', str(val_a))}</span>
      </div>
      <div style="width: 100%; height: 64px; border: 3px solid {palette.ink_a}; padding: 4px;">
        <div id="bar-a" style="height: 100%; width: 0%; background-color: {palette.ink_a};" data-target="{pct_a}%"></div>
      </div>
    </div>

    <!-- Caption in Ink A -->
    <div id="compare-caption" class="font-serif" style="margin-top: 360px; font-size: 44px; line-height: 1.45; opacity: 0;">
      {caption}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Bar B (Ink B Highlight) -->
    <div style="margin-top: 220px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 16px;">
        <span class="font-sans" style="font-size: 38px; font-weight: 700; color: {palette.ink_b};">{label_b}</span>
        <span class="font-num" style="font-size: 48px; font-weight: 700; color: {palette.ink_b};">{data.get('disp_b', str(val_b))}</span>
      </div>
      <div style="width: 100%; height: 72px; border: 3px solid {palette.ink_b}; padding: 4px;">
        <div id="bar-b" style="height: 100%; width: 0%; background-color: {palette.ink_b};" data-target="{pct_b}%"></div>
      </div>
    </div>
  </div>
"""

    elif template_name == "converge":
        inputs = data.get("inputs", ["要素一", "要素二", "要素三"])
        core = data.get("core", "最终核心")
        tag = data.get("tag", "收敛归类")

        input_html = ""
        for idx, item in enumerate(inputs):
            input_html += f"""
      <div class="conv-item" style="border: 2px solid {palette.ink_a}; padding: 18px 24px; margin-bottom: 20px; font-size: 34px; font-weight: 700; display: flex; justify-content: space-between; align-items: center;">
        <span>{item}</span>
        <span class="font-mono" style="font-size: 18px; opacity: 0.6;">0{idx+1}</span>
      </div>"""

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div class="font-mono" style="font-size: 20px; font-weight: 700; letter-spacing: 2px; margin-bottom: 36px;">
      CONVERGENCE // {tag}
    </div>

    <!-- Inputs -->
    <div id="conv-inputs">
      {input_html}
    </div>

    <!-- Convergence connector lines -->
    <div style="text-align: center; margin: 30px 0; font-size: 32px; letter-spacing: 6px;">
      ↓↓↓
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Core Target Card -->
    <div id="conv-core" style="margin-top: 480px; background-color: {palette.ink_b}; color: {palette.paper}; padding: 40px; opacity: 0; transform: scale(0.9);">
      <div class="font-mono" style="font-size: 18px; color: {palette.paper}; margin-bottom: 12px; letter-spacing: 1px;">CORE TAKEAWAY // 核心归宿</div>
      <div class="font-sans" style="font-size: 52px; font-weight: 700; line-height: 1.35; color: {palette.paper};">{core}</div>
    </div>
  </div>
"""

    elif template_name == "network":
        title = data.get("title", "系统连接密度")
        hub = data.get("hub", "核心节点")
        nodes = data.get("nodes", ["节点A", "节点B", "节点C", "节点D"])
        insight = data.get("insight", "")

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div class="font-mono" style="font-size: 20px; font-weight: 700; letter-spacing: 2px; margin-bottom: 30px;">
      NETWORK DENSITY // {title}
    </div>

    <!-- Network diagram container -->
    <svg width="860" height="600" viewBox="0 0 860 600" style="margin-bottom: 30px;">
      <!-- Connection lines -->
      <line class="net-edge" x1="430" y1="300" x2="160" y2="120" stroke="{palette.ink_a}" stroke-width="2.5" stroke-dasharray="6,4" />
      <line class="net-edge" x1="430" y1="300" x2="700" y2="120" stroke="{palette.ink_a}" stroke-width="2.5" stroke-dasharray="6,4" />
      <line class="net-edge" x1="430" y1="300" x2="180" y2="480" stroke="{palette.ink_a}" stroke-width="2.5" stroke-dasharray="6,4" />
      <line class="net-edge" x1="430" y1="300" x2="680" y2="480" stroke="{palette.ink_a}" stroke-width="2.5" stroke-dasharray="6,4" />

      <!-- Peripheral nodes in Ink A -->
      <g class="net-node" transform="translate(160, 120)">
        <circle r="44" fill="{palette.paper}" stroke="{palette.ink_a}" stroke-width="3" />
        <text text-anchor="middle" dy="8" font-size="22" font-weight="700" fill="{palette.ink_a}">{nodes[0] if len(nodes) > 0 else '01'}</text>
      </g>
      <g class="net-node" transform="translate(700, 120)">
        <circle r="44" fill="{palette.paper}" stroke="{palette.ink_a}" stroke-width="3" />
        <text text-anchor="middle" dy="8" font-size="22" font-weight="700" fill="{palette.ink_a}">{nodes[1] if len(nodes) > 1 else '02'}</text>
      </g>
      <g class="net-node" transform="translate(180, 480)">
        <circle r="44" fill="{palette.paper}" stroke="{palette.ink_a}" stroke-width="3" />
        <text text-anchor="middle" dy="8" font-size="22" font-weight="700" fill="{palette.ink_a}">{nodes[2] if len(nodes) > 2 else '03'}</text>
      </g>
      <g class="net-node" transform="translate(680, 480)">
        <circle r="44" fill="{palette.paper}" stroke="{palette.ink_a}" stroke-width="3" />
        <text text-anchor="middle" dy="8" font-size="22" font-weight="700" fill="{palette.ink_a}">{nodes[3] if len(nodes) > 3 else '04'}</text>
      </g>
    </svg>

    <div id="net-insight" class="font-serif" style="font-size: 42px; line-height: 1.4; opacity: 0;">
      {insight}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Central Hub in Ink B -->
    <div id="net-hub" style="position: absolute; top: 236px; left: 330px; width: 200px; height: 200px; border-radius: 50%; background-color: {palette.ink_b}; color: {palette.paper}; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 20px; opacity: 0; transform: scale(0.6);">
      <span class="font-mono" style="font-size: 14px; letter-spacing: 1px; color: {palette.paper}; margin-bottom: 6px;">HUB</span>
      <span class="font-sans" style="font-size: 34px; font-weight: 700; color: {palette.paper};">{hub}</span>
    </div>
  </div>
"""

    elif template_name == "focus":
        title = data.get("title", "多选一关键聚焦")
        options = data.get("options", ["选项一", "选项二", "关键选项", "选项四"])
        selected_idx = int(data.get("selected_index", 2))
        reason = data.get("reason", "")

        opt_html_a = ""
        opt_html_b = ""
        for idx, opt in enumerate(options):
            if idx == selected_idx:
                opt_html_a += f"""
      <div style="height: 100px; margin-bottom: 24px;"></div>"""
                opt_html_b = f"""
      <div id="focus-item" style="background-color: {palette.ink_b}; color: {palette.paper}; padding: 24px 30px; height: 100px; display: flex; justify-content: space-between; align-items: center; box-shadow: 4px 4px 0px {palette.ink_a};">
        <span class="font-sans" style="font-size: 38px; font-weight: 700; color: {palette.paper};">▶ {opt}</span>
        <span class="font-mono" style="font-size: 20px; color: {palette.paper};">0{idx+1} [SELECTED]</span>
      </div>"""
            else:
                opt_html_a += f"""
      <div class="focus-other" style="border: 2px solid {palette.ink_a}; padding: 24px 30px; height: 100px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; opacity: 0.65;">
        <span class="font-sans" style="font-size: 34px; font-weight: 700;">{opt}</span>
        <span class="font-mono" style="font-size: 18px; opacity: 0.6;">0{idx+1}</span>
      </div>"""

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div class="font-mono" style="font-size: 20px; font-weight: 700; letter-spacing: 2px; margin-bottom: 40px;">
      SINGLE FOCUS // {title}
    </div>

    <div>
      {opt_html_a}
    </div>

    <div id="focus-reason" class="font-serif" style="margin-top: 60px; font-size: 42px; line-height: 1.45; opacity: 0;">
      {reason}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <div style="margin-top: 60px; position: absolute; top: {60 + selected_idx * 124}px; left: 0; width: 100%; opacity: 0; transform: scale(0.95);" id="focus-highlight-wrapper">
      {opt_html_b}
    </div>
  </div>
"""

    elif template_name == "steps":
        steps_list = data.get("steps", ["积累期", "临界期", "爆发期"])
        active_step = int(data.get("active_step", 1))

        step_cards_a = ""
        active_card_b = ""

        for idx, stp in enumerate(steps_list):
            if idx == active_step:
                step_cards_a += f"""
      <div style="height: 140px; margin-bottom: 30px;"></div>"""
                active_card_b = f"""
      <div id="active-step-card" style="background-color: {palette.ink_b}; color: {palette.paper}; padding: 30px 36px; height: 140px; display: flex; align-items: center; gap: 24px; opacity: 0; transform: translateY(20px);">
        <span class="font-num" style="font-size: 64px; font-weight: 700; color: {palette.paper};">0{idx+1}</span>
        <div>
          <div class="font-mono" style="font-size: 16px; color: {palette.paper}; opacity: 0.85;">CURRENT FOCUS // 当前重心</div>
          <div class="font-sans" style="font-size: 42px; font-weight: 700; color: {palette.paper};">{stp}</div>
        </div>
      </div>"""
            else:
                step_cards_a += f"""
      <div class="step-card" style="border: 2px solid {palette.ink_a}; padding: 30px 36px; height: 140px; margin-bottom: 30px; display: flex; align-items: center; gap: 24px; opacity: 0.7;">
        <span class="font-num" style="font-size: 54px; font-weight: 700;">0{idx+1}</span>
        <div class="font-sans" style="font-size: 38px; font-weight: 700;">{stp}</div>
      </div>"""

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div class="font-mono" style="font-size: 20px; font-weight: 700; letter-spacing: 2px; margin-bottom: 50px;">
      PHASE SEQUENCE // 流程步骤
    </div>

    <div>
      {step_cards_a}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <div style="position: absolute; top: {70 + active_step * 170}px; left: 0; width: 100%;" id="step-b-wrapper">
      {active_card_b}
    </div>
  </div>
"""

    elif template_name == "shot":
        # Rule: "shot 截图锚点（没有截图就显示「待替换」占位，禁止用代码画仿造界面）"
        caption = data.get("caption", "数据凭证")
        tag = data.get("tag", "SCREENSHOT")
        image_url = data.get("image_url", "")

        if image_url:
            content_display = f'<img src="{image_url}" style="width: 100%; height: 100%; object-fit: contain;" alt="screenshot">'
        else:
            # STRICT technical placeholder box, FORBIDDEN to fake UI elements with code!
            content_display = f"""
      <div style="width: 100%; height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; border: 2px dashed {palette.ink_a}; background: rgba(0,0,0,0.02);">
        <div class="font-mono" style="font-size: 36px; font-weight: 700; letter-spacing: 4px; margin-bottom: 12px;">[ 待替换 ]</div>
        <div class="font-mono" style="font-size: 18px; opacity: 0.6;">SCREENSHOT_PLACEHOLDER // 1080x720</div>
      </div>"""

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px;">
      <span class="font-mono" style="font-size: 20px; font-weight: 700; border: 2px solid {palette.ink_a}; padding: 4px 12px;">{tag}</span>
      <span class="font-mono" style="font-size: 16px; opacity: 0.6;">ANCHOR FRAME</span>
    </div>

    <!-- Screenshot Container Frame -->
    <div id="shot-frame" style="width: 860px; height: 560px; border: 3px solid {palette.ink_a}; padding: 16px; position: relative; opacity: 0; transform: scale(0.96);">
      {content_display}
    </div>

    <!-- Caption -->
    <div id="shot-caption" class="font-serif" style="margin-top: 40px; font-size: 44px; line-height: 1.4; opacity: 0;">
      {caption}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Ink B Technical corner stamp -->
    <div id="shot-corner" style="position: absolute; top: 72px; right: 0; border: 3px solid {palette.ink_b}; color: {palette.ink_b}; padding: 8px 16px; font-size: 18px; font-weight: 700; opacity: 0;">
      VERIFIED // 凭证
    </div>
  </div>
"""

    elif template_name == "quote":
        quote_text = data.get("quote", "")
        author = data.get("author", "口播金句")

        return f"""
  <div class="ink-layer ink-a" id="stage-ink-a">
    <!-- Quote Text -->
    <div id="quote-text" class="font-serif" style="margin-top: 180px; font-size: 56px; line-height: 1.5; font-weight: 700; opacity: 0; transform: translateY(30px);">
      {quote_text}
    </div>

    <!-- Author/Citation -->
    <div id="quote-author" class="font-mono" style="margin-top: 60px; font-size: 22px; font-weight: 700; border-top: 2px solid {palette.ink_a}; padding-top: 20px; opacity: 0;">
      —— {author}
    </div>
  </div>

  <div class="ink-layer ink-b" id="stage-ink-b">
    <!-- Giant Riso Quote Mark in Ink B -->
    <div id="quote-mark" class="font-serif" style="position: absolute; top: 0; left: -10px; font-size: 180px; line-height: 0.8; color: {palette.ink_b}; opacity: 0; transform: scale(0.7);">
      “
    </div>
  </div>
"""

    return "<div>Template not found</div>"


def _render_template_animation(template_name: str) -> str:
    """GSAP animation scripting ensuring climax settles within 2.5s and holds."""
    if template_name == "versus":
        return """
  // Phase 1 (0.0s - 0.7s): Ink A myth box prints down
  window.tl.fromTo("#stage-ink-a", { opacity: 0, y: -20 }, { opacity: 1, y: 0, duration: 0.6, ease: "power2.out" }, 0.0);
  // Phase 2 (0.7s - 1.2s): Strikethrough myth
  window.tl.to("#strike-line", { width: "85%", duration: 0.45, ease: "power3.inOut" }, 0.7);
  // Phase 3 (1.2s - 2.0s): CLIMAX! Ink B Reality stamps with registration settle
  window.tl.to("#reality-box", { opacity: 1, y: 0, duration: 0.6, ease: "back.out(1.4)" }, 1.2);
  // Settle & hold from 2.0s to 3.5s+
"""

    elif template_name == "title":
        return """
  window.tl.to("#title-num", { opacity: 1, y: 0, duration: 0.65, ease: "power2.out" }, 0.1);
  window.tl.to("#title-main", { opacity: 1, duration: 0.7, ease: "power2.out" }, 0.45);
  // Climax: Ink B Subtitle stamp
  window.tl.to("#title-sub", { opacity: 1, x: 0, duration: 0.6, ease: "back.out(1.2)" }, 1.2);
"""

    elif template_name == "number":
        return """
  window.tl.to("#num-giant", { opacity: 1, scale: 1.0, duration: 0.8, ease: "elastic.out(1.0, 0.7)" }, 0.2);
  window.tl.to("#num-insight", { opacity: 1, duration: 0.6, ease: "power2.out" }, 1.2);
"""

    elif template_name == "compare":
        return """
  const targetA = document.getElementById("bar-a").getAttribute("data-target") || "40%";
  const targetB = document.getElementById("bar-b").getAttribute("data-target") || "100%";
  window.tl.to("#bar-a", { width: targetA, duration: 0.9, ease: "power2.out" }, 0.3);
  window.tl.to("#bar-b", { width: targetB, duration: 1.0, ease: "power2.out" }, 0.6);
  window.tl.to("#compare-caption", { opacity: 1, duration: 0.6, ease: "power2.out" }, 1.4);
"""

    elif template_name == "converge":
        return """
  window.tl.from(".conv-item", { opacity: 0, x: -30, stagger: 0.2, duration: 0.5, ease: "power2.out" }, 0.2);
  // Climax: Core takeaway stamps into focus
  window.tl.to("#conv-core", { opacity: 1, scale: 1.0, duration: 0.7, ease: "back.out(1.5)" }, 1.1);
"""

    elif template_name == "network":
        return """
  window.tl.from(".net-edge", { strokeDashoffset: 100, duration: 0.8, ease: "power2.out" }, 0.2);
  window.tl.from(".net-node", { opacity: 0, scale: 0.5, stagger: 0.15, duration: 0.5, ease: "back.out(1.2)" }, 0.4);
  // Climax: Hub in Ink B expands and stabilizes
  window.tl.to("#net-hub", { opacity: 1, scale: 1.0, duration: 0.75, ease: "elastic.out(1.0, 0.6)" }, 1.0);
  window.tl.to("#net-insight", { opacity: 1, duration: 0.6, ease: "power2.out" }, 1.5);
"""

    elif template_name == "focus":
        return """
  window.tl.from(".focus-other", { opacity: 0, y: 15, stagger: 0.15, duration: 0.5, ease: "power2.out" }, 0.2);
  // Climax: Highlight box snaps into place
  window.tl.to("#focus-highlight-wrapper", { opacity: 1, scale: 1.0, duration: 0.6, ease: "back.out(1.4)" }, 0.9);
  window.tl.to("#focus-reason", { opacity: 1, duration: 0.6, ease: "power2.out" }, 1.4);
"""

    elif template_name == "steps":
        return """
  window.tl.from(".step-card", { opacity: 0, y: 20, stagger: 0.2, duration: 0.6, ease: "power2.out" }, 0.2);
  // Climax: Active step prints down
  window.tl.to("#active-step-card", { opacity: 1, y: 0, duration: 0.6, ease: "back.out(1.3)" }, 1.1);
"""

    elif template_name == "shot":
        return """
  window.tl.to("#shot-frame", { opacity: 1, scale: 1.0, duration: 0.7, ease: "power2.out" }, 0.2);
  window.tl.to("#shot-corner", { opacity: 1, duration: 0.4, ease: "power2.out" }, 0.8);
  window.tl.to("#shot-caption", { opacity: 1, duration: 0.6, ease: "power2.out" }, 1.2);
"""

    elif template_name == "quote":
        return """
  window.tl.to("#quote-mark", { opacity: 1, scale: 1.0, duration: 0.7, ease: "back.out(1.4)" }, 0.2);
  window.tl.to("#quote-text", { opacity: 1, y: 0, duration: 0.7, ease: "power2.out" }, 0.6);
  window.tl.to("#quote-author", { opacity: 1, duration: 0.6, ease: "power2.out" }, 1.3);
"""

    return ""
