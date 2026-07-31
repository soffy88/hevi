"""动效模板库 — 对标 hyperframes-motion-library。

20 个可复用视频动效模板,参数化数据驱动,支持透明导出。
每个模板: HTML 源码 + 变量声明 + 默认预设 + 目录登记。
渲染后端复用 hevi.video.hyperframes_service。

参考: https://github.com/nutllwhy/hyperframes-motion-library
"""
from __future__ import annotations

import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hevi.video.hyperframes_service import render_html_video

logger = logging.getLogger(__name__)

__all__ = [
    "MotionTemplateId",
    "MotionVariable",
    "MotionTemplate",
    "MotionPreset",
    "MotionRenderRequest",
    "MotionRenderResult",
    "MotionCatalog",
    "get_catalog",
    "get_template",
    "list_presets",
    "render_motion",
    "render_with_preset",
]


# ---------------------------------------------------------------------------
# Enums & Models
# ---------------------------------------------------------------------------


class MotionTemplateId(str, Enum):
    """20 个模板 ID。"""

    # Data Visualization (6)
    METRIC_PULSE = "metric-pulse"
    BAR_CHART_RACE = "bar-chart-race"
    LINE_CHART_DRAW = "line-chart-draw"
    PIE_CHART_SPIN = "pie-chart-spin"
    DATA_PULSE = "data-pulse"
    RADAR_CHART = "radar-chart"

    # Transparent Overlay (6)
    LOWER_THIRD = "lower-third"
    QUOTE_CARD = "quote-card"
    CALL_TO_ACTION = "call-to-action"
    PROGRESS_BAR = "progress-bar"
    NOTIFICATION_TOAST = "notification-toast"
    FLOATING_LABEL = "floating-label"

    # Knowledge / Explainer (5)
    TIMELINE_SLIDE = "timeline-slide"
    STEP_BY_STEP = "step-by-step"
    COMPARISON_SPLIT = "comparison-split"
    DEFINITION_CARD = "definition-card"
    KEY_TAKEAWAY = "key-takeaway"

    # Transition / Effect (3)
    PARTICLE_BURST = "particle-burst"
    GLITCH_TEXT = "glitch-text"
    CINEMATIC_BARS = "cinematic-bars"


class MotionVariable(BaseModel):
    """模板变量声明。"""

    name: str
    type: str = Field(description="text | number | color | image")
    default_value: str
    description: str = ""


class MotionPreset(BaseModel):
    """预设:一组填充变量值的命名配置。"""

    name: str
    variables: dict[str, Any]
    description: str = ""


class MotionTemplate(BaseModel):
    """单个动效模板完整定义。"""

    id: str
    name: str
    category: str
    description: str
    html_source: str
    gsap_script: str
    variables: list[MotionVariable]
    default_preset: MotionPreset
    supports_transparent: bool = False


class MotionRenderRequest(BaseModel):
    """渲染请求。"""

    template_id: str
    preset_name: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    width: int = 1920
    height: int = 1080
    fps: int = 24
    duration: float = 5.0
    output_format: str = Field(default="mp4", description="mp4 | mov | webm")
    transparent: bool = False


class MotionRenderResult(BaseModel):
    """渲染结果。"""

    output_path: Path | None = None
    template_id: str
    preset_name: str | None = None
    duration: float = 0.0
    success: bool = False
    error: str | None = None


class MotionCatalog(BaseModel):
    """模板目录,支持按 category / keyword 搜索。"""

    templates: list[MotionTemplate]
    categories: list[str] = Field(default_factory=list)

    def search(self, query: str) -> list[MotionTemplate]:
        q = query.lower()
        return [
            t for t in self.templates
            if q in t.id.lower()
            or q in t.name.lower()
            or q in t.description.lower()
            or q in t.category.lower()
        ]

    def get_by_category(self, category: str) -> list[MotionTemplate]:
        return [t for t in self.templates if t.category == category]

    def get(self, template_id: str) -> MotionTemplate | None:
        for t in self.templates:
            if t.id == template_id:
                return t
        return None


# ---------------------------------------------------------------------------
# Template HTML / GSAP definitions
# ---------------------------------------------------------------------------

# Helper: shared CSS reset injected into every template body
_BODY_RESET = "margin:0;padding:0;box-sizing:border-box;"
_GSAP_CDN = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"

_TEMPLATE_DEFS: list[dict[str, Any]] = [
    # =======================================================================
    # 1. metric-pulse — 数字跳动计数器
    # =======================================================================
    {
        "id": "metric-pulse",
        "name": "数字跳动计数器",
        "category": "Data Visualization",
        "description": "大数字跳动动画,支持前缀/后缀,脉冲高亮",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="value", type="number", default_value="98600",
                           description="目标数值"),
            MotionVariable(name="label", type="text", default_value="Total Revenue",
                           description="指标名称"),
            MotionVariable(name="prefix", type="text", default_value="$",
                           description="前缀符号"),
            MotionVariable(name="suffix", type="text", default_value="",
                           description="后缀符号"),
            MotionVariable(name="color", type="color", default_value="#00E5FF",
                           description="主色调"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div class="mp-label" style="font-size:28px;color:#aaa;letter-spacing:4px;text-transform:uppercase;margin-bottom:20px;opacity:0;">{{{{label}}}}</div>
  <div class="mp-value" style="font-size:120px;font-weight:800;color:{{{{color}}}};line-height:1;opacity:0;">
    <span class="mp-prefix">{{{{prefix}}}}</span><span class="mp-num">0</span><span class="mp-suffix">{{{{suffix}}}}</span>
  </div>
  <div class="mp-bar" style="width:200px;height:4px;background:rgba(255,255,255,0.1);margin-top:30px;border-radius:2px;overflow:hidden;">
    <div class="mp-bar-fill" style="width:0%;height:100%;background:{{{{color}}}};border-radius:2px;"></div>
  </div>
</div>''',
        "gsap_script": '''
const target = parseInt("{{value}}", 10) || 0;
const numEl = document.querySelector(".mp-num");
const obj = {v: 0};
gsap.timeline()
  .to(".mp-label", {opacity:1, y:0, duration:0.5, ease:"power2.out"})
  .to(".mp-value", {opacity:1, scale:1, duration:0.4, ease:"back.out(1.7)"}, "-=0.2")
  .to(obj, {v: target, duration:2, ease:"power2.out",
    onUpdate: () => { numEl.textContent = Math.round(obj.v).toLocaleString(); }
  }, "-=0.3")
  .to(".mp-bar-fill", {width:"100%", duration:2, ease:"power2.out"}, "-=2")
  .to(".mp-value", {scale:1.05, duration:0.3, yoyo:true, repeat:1, ease:"power1.inOut"});
''',
        "default_preset": MotionPreset(
            name="revenue",
            variables={"value": "98600", "label": "Total Revenue",
                       "prefix": "$", "suffix": "", "color": "#00E5FF"},
            description="收入指标展示",
        ),
    },

    # =======================================================================
    # 2. bar-chart-race — 横向柱状图竞赛
    # =======================================================================
    {
        "id": "bar-chart-race",
        "name": "横向柱状图竞赛",
        "category": "Data Visualization",
        "description": "多条目横向柱状图竞赛动画,自动排序",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="items", type="text",
                           default_value='[{"name":"Alpha","value":85,"color":"#FF6B6B"},{"name":"Beta","value":72,"color":"#4ECDC4"},{"name":"Gamma","value":93,"color":"#45B7D1"},{"name":"Delta","value":61,"color":"#96CEB4"}]',
                           description="JSON array of {name,value,color}"),
            MotionVariable(name="title", type="text", default_value="Market Share",
                           description="图表标题"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;padding:60px 80px;background:#0f0f1a;font-family:'Inter',system-ui,sans-serif;">
  <h2 class="bcr-title" style="font-size:36px;color:#fff;margin-bottom:40px;opacity:0;">{{{{title}}}}</h2>
  <div class="bcr-bars" style="flex:1;display:flex;flex-direction:column;justify-content:space-around;"></div>
</div>
<script>
(function() {{
  const items = {{{{items}}}};
  const container = document.querySelector(".bcr-bars");
  const maxVal = Math.max(...items.map(i => i.value));
  items.forEach((item, i) => {{
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;margin-bottom:16px;opacity:0;transform:translateX(-40px);";
    row.className = "bcr-row";
    row.innerHTML = '<span style="width:120px;color:#ccc;font-size:18px;text-align:right;margin-right:16px;">' + item.name + '</span>'
      + '<div style="flex:1;height:36px;background:rgba(255,255,255,0.05);border-radius:6px;overflow:hidden;">'
      + '<div class="bcr-fill" style="width:0%;height:100%;background:' + item.color + ';border-radius:6px;display:flex;align-items:center;justify-content:flex-end;padding-right:12px;">'
      + '<span style="color:#fff;font-weight:700;font-size:14px;opacity:0;" class="bcr-val">' + item.value + '</span></div></div>';
    container.appendChild(row);
  }});
}})();
</script>''',
        "gsap_script": '''
gsap.to(".bcr-title", {opacity:1, duration:0.5});
const rows = document.querySelectorAll(".bcr-row");
const items = {{items}};
const maxVal = Math.max(...items.map(i => i.value));
rows.forEach((row, i) => {
  const pct = (items[i].value / maxVal) * 100;
  gsap.timeline({delay: 0.3 + i * 0.15})
    .to(row, {opacity:1, x:0, duration:0.4, ease:"power2.out"})
    .to(row.querySelector(".bcr-fill"), {width: pct + "%", duration:1.2, ease:"power2.out"})
    .to(row.querySelector(".bcr-val"), {opacity:1, duration:0.3}, "-=0.3");
});
''',
        "default_preset": MotionPreset(
            name="market-share",
            variables={
                "items": '[{"name":"Alpha","value":85,"color":"#FF6B6B"},{"name":"Beta","value":72,"color":"#4ECDC4"},{"name":"Gamma","value":93,"color":"#45B7D1"},{"name":"Delta","value":61,"color":"#96CEB4"}]',
                "title": "Market Share",
            },
            description="四品牌市占率竞赛",
        ),
    },

    # =======================================================================
    # 3. line-chart-draw — 折线图绘制动画
    # =======================================================================
    {
        "id": "line-chart-draw",
        "name": "折线图绘制动画",
        "category": "Data Visualization",
        "description": "SVG 折线图逐步绘制,带坐标轴和数据点",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="points", type="text",
                           default_value="[12,28,45,38,62,78,55,90,85,110]",
                           description="数据点数组 (JSON)"),
            MotionVariable(name="title", type="text", default_value="Growth Trend",
                           description="图表标题"),
            MotionVariable(name="x_label", type="text", default_value="Month",
                           description="X 轴标签"),
            MotionVariable(name="y_label", type="text", default_value="Revenue ($K)",
                           description="Y 轴标签"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;padding:50px 70px;background:#0a0a1a;font-family:'Inter',system-ui,sans-serif;">
  <h2 class="lcd-title" style="font-size:32px;color:#fff;margin-bottom:10px;opacity:0;">{{{{title}}}}</h2>
  <div style="flex:1;position:relative;">
    <svg class="lcd-svg" width="100%" height="100%" viewBox="0 0 800 400" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="lcd-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#00E5FF" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#00E5FF" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <!-- grid -->
      <g class="lcd-grid" opacity="0">
        <line x1="60" y1="20" x2="60" y2="360" stroke="#333" stroke-width="1"/>
        <line x1="60" y1="360" x2="780" y2="360" stroke="#333" stroke-width="1"/>
      </g>
      <!-- labels -->
      <text class="lcd-xlabel" x="420" y="395" fill="#888" font-size="14" text-anchor="middle" opacity="0">{{{{x_label}}}}</text>
      <text class="lcd-ylabel" x="15" y="190" fill="#888" font-size="14" text-anchor="middle" transform="rotate(-90,15,190)" opacity="0">{{{{y_label}}}}</text>
      <!-- area fill -->
      <path class="lcd-area" d="" fill="url(#lcd-grad)" opacity="0"/>
      <!-- line -->
      <path class="lcd-line" d="" fill="none" stroke="#00E5FF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      <!-- dots -->
      <g class="lcd-dots"></g>
    </svg>
  </div>
</div>''',
        "gsap_script": '''
const data = {{points}};
const maxV = Math.max(...data);
const padL=60, padR=20, padT=20, padB=40, W=800, H=400;
const chartW = W - padL - padR, chartH = H - padT - padB;
const pts = data.map((v,i) => {
  const x = padL + (i / (data.length-1)) * chartW;
  const y = padT + chartH - (v / maxV) * chartH;
  return {x, y};
});
const lineD = pts.map((p,i) => (i===0?"M":"L") + p.x + " " + p.y).join(" ");
const areaD = lineD + " L" + pts[pts.length-1].x + " " + (padT+chartH) + " L" + pts[0].x + " " + (padT+chartH) + " Z";
document.querySelector(".lcd-line").setAttribute("d", lineD);
document.querySelector(".lcd-area").setAttribute("d", areaD);
const dotsG = document.querySelector(".lcd-dots");
pts.forEach(p => {
  const c = document.createElementNS("http://www.w3.org/2000/svg","circle");
  c.setAttribute("cx", p.x); c.setAttribute("cy", p.y);
  c.setAttribute("r","5"); c.setAttribute("fill","#00E5FF");
  c.style.opacity = "0";
  dotsG.appendChild(c);
});
const lineEl = document.querySelector(".lcd-line");
const totalLen = lineEl.getTotalLength();
lineEl.style.strokeDasharray = totalLen;
lineEl.style.strokeDashoffset = totalLen;
const tl = gsap.timeline();
tl.to(".lcd-title", {opacity:1, duration:0.4})
  .to(".lcd-grid", {opacity:1, duration:0.3})
  .to(".lcd-xlabel", {opacity:1, duration:0.3}, "-=0.1")
  .to(".lcd-ylabel", {opacity:1, duration:0.3}, "-=0.2")
  .to(lineEl, {strokeDashoffset:0, duration:2, ease:"power1.inOut"})
  .to(".lcd-area", {opacity:1, duration:0.8}, "-=1")
  .to(".lcd-dots circle", {opacity:1, duration:0.2, stagger:0.08}, "-=1.2");
''',
        "default_preset": MotionPreset(
            name="growth",
            variables={
                "points": "[12,28,45,38,62,78,55,90,85,110]",
                "title": "Growth Trend",
                "x_label": "Month",
                "y_label": "Revenue ($K)",
            },
            description="月度增长趋势",
        ),
    },

    # =======================================================================
    # 4. pie-chart-spin — 饼图旋转展开
    # =======================================================================
    {
        "id": "pie-chart-spin",
        "name": "饼图旋转展开",
        "category": "Data Visualization",
        "description": "SVG 饼图扇区依次旋转展开",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="segments", type="text",
                           default_value='[{"name":"Product A","value":35,"color":"#FF6B6B"},{"name":"Product B","value":25,"color":"#4ECDC4"},{"name":"Product C","value":20,"color":"#45B7D1"},{"name":"Product D","value":20,"color":"#FFE66D"}]',
                           description="JSON array of {name,value,color}"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div style="display:flex;align-items:center;gap:80px;">
    <svg class="pcs-svg" width="400" height="400" viewBox="-200 -200 400 400"></svg>
    <div class="pcs-legend" style="display:flex;flex-direction:column;gap:16px;"></div>
  </div>
</div>
<script>
(function() {{
  const segs = {{{{segments}}}};
  const total = segs.reduce((s,x) => s + x.value, 0);
  const svg = document.querySelector(".pcs-svg");
  const legend = document.querySelector(".pcs-legend");
  let cumAngle = -90;
  segs.forEach((seg, i) => {{
    const angle = (seg.value / total) * 360;
    const startRad = cumAngle * Math.PI / 180;
    const endRad = (cumAngle + angle) * Math.PI / 180;
    const largeArc = angle > 180 ? 1 : 0;
    const x1 = 160 * Math.cos(startRad), y1 = 160 * Math.sin(startRad);
    const x2 = 160 * Math.cos(endRad), y2 = 160 * Math.sin(endRad);
    const path = document.createElementNS("http://www.w3.org/2000/svg","path");
    path.setAttribute("d", "M0 0 L" + x1 + " " + y1 + " A160 160 0 " + largeArc + " 1 " + x2 + " " + y2 + " Z");
    path.setAttribute("fill", seg.color);
    path.style.opacity = "0";
    path.style.transformOrigin = "center";
    path.className.baseVal = "pcs-seg";
    svg.appendChild(path);
    cumAngle += angle;
    // legend
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:10px;opacity:0;";
    row.className = "pcs-leg-row";
    row.innerHTML = '<div style="width:16px;height:16px;border-radius:3px;background:' + seg.color + ';"></div>'
      + '<span style="color:#ccc;font-size:16px;">' + seg.name + '</span>'
      + '<span style="color:#fff;font-weight:700;margin-left:8px;">' + Math.round(seg.value/total*100) + '%</span>';
    legend.appendChild(row);
  }});
}})();
</script>''',
        "gsap_script": '''
gsap.fromTo(".pcs-svg", {rotation: -180}, {rotation:0, duration:1.5, ease:"power2.out"});
gsap.to(".pcs-seg", {opacity:1, duration:0.4, stagger:0.2, delay:0.3, ease:"power2.out"});
gsap.to(".pcs-leg-row", {opacity:1, x:0, duration:0.3, stagger:0.15, delay:0.8, ease:"power2.out"});
''',
        "default_preset": MotionPreset(
            name="product-split",
            variables={
                "segments": '[{"name":"Product A","value":35,"color":"#FF6B6B"},{"name":"Product B","value":25,"color":"#4ECDC4"},{"name":"Product C","value":20,"color":"#45B7D1"},{"name":"Product D","value":20,"color":"#FFE66D"}]',
            },
            description="产品占比饼图",
        ),
    },

    # =======================================================================
    # 5. data-pulse — 数据脉冲卡片
    # =======================================================================
    {
        "id": "data-pulse",
        "name": "数据脉冲卡片",
        "category": "Data Visualization",
        "description": "多指标数据卡片,数值依次脉冲高亮",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="metrics", type="text",
                           default_value='[{"label":"Active Users","value":"12.4K","change":"+18%"},{"label":"Conversion","value":"3.2%","change":"+0.5%"},{"label":"Revenue","value":"$84K","change":"+22%"}]',
                           description="JSON array of {label,value,change}"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;gap:40px;padding:60px;background:transparent;font-family:'Inter',system-ui,sans-serif;">
</div>
<script>
(function() {{
  const metrics = {{{{metrics}}}};
  const container = document.querySelector("div");
  metrics.forEach(m => {{
    const card = document.createElement("div");
    card.className = "dp-card";
    card.style.cssText = "background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:36px 44px;min-width:240px;text-align:center;opacity:0;transform:translateY(30px);backdrop-filter:blur(10px);";
    const isUp = m.change.startsWith("+");
    card.innerHTML = '<div style="font-size:14px;color:#999;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;">' + m.label + '</div>'
      + '<div class="dp-val" style="font-size:48px;font-weight:800;color:#fff;line-height:1.2;">' + m.value + '</div>'
      + '<div style="font-size:16px;color:' + (isUp ? '#4ADE80' : '#F87171') + ';margin-top:8px;">' + m.change + '</div>';
    container.appendChild(card);
  }});
}})();
</script>''',
        "gsap_script": '''
gsap.to(".dp-card", {
  opacity:1, y:0, duration:0.6, stagger:0.2, ease:"back.out(1.5)"
});
gsap.utils.toArray(".dp-val").forEach((el, i) => {
  gsap.to(el, {scale:1.1, duration:0.3, delay: 0.8 + i*0.2, yoyo:true, repeat:1, ease:"power1.inOut"});
});
''',
        "default_preset": MotionPreset(
            name="dashboard",
            variables={
                "metrics": '[{"label":"Active Users","value":"12.4K","change":"+18%"},{"label":"Conversion","value":"3.2%","change":"+0.5%"},{"label":"Revenue","value":"$84K","change":"+22%"}]',
            },
            description="仪表盘数据卡片",
        ),
    },

    # =======================================================================
    # 6. radar-chart — 雷达图展开
    # =======================================================================
    {
        "id": "radar-chart",
        "name": "雷达图展开",
        "category": "Data Visualization",
        "description": "SVG 雷达图从中心向外展开,带轴线标签",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="axes", type="text",
                           default_value='["Speed","Quality","Cost","Innovation","Reliability"]',
                           description="雷达轴名称 (JSON array)"),
            MotionVariable(name="values", type="text",
                           default_value="[0.8,0.65,0.9,0.7,0.85]",
                           description="各轴 0-1 归一化值"),
            MotionVariable(name="label", type="text", default_value="Performance",
                           description="图表标签"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div class="rc-label" style="font-size:28px;color:#fff;margin-bottom:20px;opacity:0;">{{{{label}}}}</div>
  <svg class="rc-svg" width="500" height="500" viewBox="-250 -250 500 500"></svg>
</div>
<script>
(function() {{
  const axes = {{{{axes}}}};
  const vals = {{{{values}}}};
  const svg = document.querySelector(".rc-svg");
  const R = 180, n = axes.length;
  // grid rings
  [0.25, 0.5, 0.75, 1.0].forEach(r => {{
    const pts = [];
    for (let i = 0; i < n; i++) {{
      const a = (Math.PI*2*i/n) - Math.PI/2;
      pts.push((R*r*Math.cos(a)).toFixed(1) + "," + (R*r*Math.sin(a)).toFixed(1));
    }}
    const poly = document.createElementNS("http://www.w3.org/2000/svg","polygon");
    poly.setAttribute("points", pts.join(" "));
    poly.setAttribute("fill","none"); poly.setAttribute("stroke","rgba(255,255,255,0.1)");
    poly.className.baseVal = "rc-ring"; poly.style.opacity = "0";
    svg.appendChild(poly);
  }});
  // axes + labels
  for (let i = 0; i < n; i++) {{
    const a = (Math.PI*2*i/n) - Math.PI/2;
    const lx = (R+30)*Math.cos(a), ly = (R+30)*Math.sin(a);
    const line = document.createElementNS("http://www.w3.org/2000/svg","line");
    line.setAttribute("x1","0"); line.setAttribute("y1","0");
    line.setAttribute("x2", (R*Math.cos(a)).toFixed(1));
    line.setAttribute("y2", (R*Math.sin(a)).toFixed(1));
    line.setAttribute("stroke","rgba(255,255,255,0.15)"); line.className.baseVal = "rc-axis";
    line.style.opacity = "0";
    svg.appendChild(line);
    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", lx.toFixed(1)); txt.setAttribute("y", (ly+5).toFixed(1));
    txt.setAttribute("fill","#ccc"); txt.setAttribute("font-size","14");
    txt.setAttribute("text-anchor","middle"); txt.textContent = axes[i];
    txt.className.baseVal = "rc-lbl"; txt.style.opacity = "0";
    svg.appendChild(txt);
  }}
  // data polygon
  const dataPts = [];
  for (let i = 0; i < n; i++) {{
    const a = (Math.PI*2*i/n) - Math.PI/2;
    const r = R * vals[i];
    dataPts.push((r*Math.cos(a)).toFixed(1) + "," + (r*Math.sin(a)).toFixed(1));
  }}
  const dataPoly = document.createElementNS("http://www.w3.org/2000/svg","polygon");
  dataPoly.setAttribute("points", dataPts.join(" "));
  dataPoly.setAttribute("fill","rgba(0,229,255,0.25)");
  dataPoly.setAttribute("stroke","#00E5FF"); dataPoly.setAttribute("stroke-width","2");
  dataPoly.className.baseVal = "rc-data"; dataPoly.style.opacity = "0";
  svg.appendChild(dataPoly);
}})();
</script>''',
        "gsap_script": '''
gsap.to(".rc-label", {opacity:1, duration:0.4});
gsap.to(".rc-ring", {opacity:1, duration:0.3, stagger:0.1, delay:0.2});
gsap.to(".rc-axis", {opacity:1, duration:0.2, stagger:0.08, delay:0.4});
gsap.to(".rc-lbl", {opacity:1, duration:0.2, stagger:0.08, delay:0.6});
gsap.to(".rc-data", {opacity:1, duration:0.8, delay:0.9, ease:"power2.out"});
gsap.from(".rc-data", {attr:{points:"0,0 0,0 0,0 0,0 0,0"}, duration:1, delay:0.9, ease:"power2.out"});
''',
        "default_preset": MotionPreset(
            name="performance",
            variables={
                "axes": '["Speed","Quality","Cost","Innovation","Reliability"]',
                "values": "[0.8,0.65,0.9,0.7,0.85]",
                "label": "Performance",
            },
            description="五维性能雷达图",
        ),
    },

    # =======================================================================
    # 7. lower-third — 字幕条
    # =======================================================================
    {
        "id": "lower-third",
        "name": "字幕条",
        "category": "Transparent Overlay",
        "description": "底部字幕条,含姓名/标题/副标题,支持透明背景叠加",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="name", type="text", default_value="Sarah Chen",
                           description="人物姓名"),
            MotionVariable(name="title", type="text", default_value="Chief Technology Officer",
                           description="职位标题"),
            MotionVariable(name="subtitle", type="text", default_value="AI & Cloud Infrastructure",
                           description="副标题说明"),
            MotionVariable(name="accent_color", type="color", default_value="#00E5FF",
                           description="强调色"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:flex-end;padding:80px;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div class="lt-wrap" style="display:flex;align-items:stretch;opacity:0;transform:translateX(-100px);">
    <div class="lt-accent" style="width:6px;background:{{{{accent_color}}}};border-radius:3px 0 0 3px;"></div>
    <div style="background:rgba(0,0,0,0.75);backdrop-filter:blur(16px);padding:24px 36px;border-radius:0 12px 12px 0;min-width:400px;">
      <div class="lt-name" style="font-size:32px;font-weight:700;color:#fff;opacity:0;">{{{{name}}}}</div>
      <div class="lt-title" style="font-size:18px;color:{{{{accent_color}}}};margin-top:4px;opacity:0;">{{{{title}}}}</div>
      <div class="lt-sub" style="font-size:14px;color:#999;margin-top:2px;opacity:0;">{{{{subtitle}}}}</div>
    </div>
  </div>
</div>''',
        "gsap_script": '''
gsap.timeline()
  .to(".lt-wrap", {opacity:1, x:0, duration:0.6, ease:"power3.out"})
  .to(".lt-name", {opacity:1, duration:0.3}, "-=0.2")
  .to(".lt-title", {opacity:1, duration:0.3}, "-=0.1")
  .to(".lt-sub", {opacity:1, duration:0.3}, "-=0.1");
''',
        "default_preset": MotionPreset(
            name="interview",
            variables={"name": "Sarah Chen", "title": "Chief Technology Officer",
                       "subtitle": "AI & Cloud Infrastructure", "accent_color": "#00E5FF"},
            description="采访嘉宾字幕条",
        ),
    },

    # =======================================================================
    # 8. quote-card — 引用卡片
    # =======================================================================
    {
        "id": "quote-card",
        "name": "引用卡片",
        "category": "Transparent Overlay",
        "description": "大引号引用卡片,逐字显示文本",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="quote", type="text",
                           default_value="The best way to predict the future is to create it.",
                           description="引用文本"),
            MotionVariable(name="author", type="text", default_value="Peter Drucker",
                           description="作者"),
            MotionVariable(name="style", type="text", default_value="minimal",
                           description="风格: minimal | bold | elegant"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:transparent;font-family:'Georgia',serif;">
  <div class="qc-card" style="max-width:900px;text-align:center;padding:60px;opacity:0;">
    <div class="qc-mark" style="font-size:120px;line-height:0.5;color:rgba(255,255,255,0.15);font-family:Georgia,serif;">\u201c</div>
    <p class="qc-text" style="font-size:36px;line-height:1.6;color:#fff;font-style:italic;margin:20px 0;letter-spacing:0.5px;">{{{{quote}}}}</p>
    <div class="qc-line" style="width:0;height:2px;background:rgba(255,255,255,0.3);margin:24px auto;"></div>
    <p class="qc-author" style="font-size:20px;color:#aaa;letter-spacing:3px;text-transform:uppercase;opacity:0;">— {{{{author}}}}</p>
  </div>
</div>''',
        "gsap_script": '''
gsap.timeline()
  .to(".qc-card", {opacity:1, scale:1, duration:0.6, ease:"power2.out"})
  .to(".qc-mark", {color:"rgba(255,255,255,0.4)", duration:0.5}, "-=0.3")
  .from(".qc-text", {opacity:0, y:20, duration:0.8, ease:"power2.out"}, "-=0.3")
  .to(".qc-line", {width:"80px", duration:0.5, ease:"power2.inOut"})
  .to(".qc-author", {opacity:1, duration:0.4}, "-=0.2");
''',
        "default_preset": MotionPreset(
            name="inspirational",
            variables={
                "quote": "The best way to predict the future is to create it.",
                "author": "Peter Drucker",
                "style": "minimal",
            },
            description="经典名言引用",
        ),
    },

    # =======================================================================
    # 9. call-to-action — CTA 按钮
    # =======================================================================
    {
        "id": "call-to-action",
        "name": "CTA 按钮",
        "category": "Transparent Overlay",
        "description": "行动号召按钮,脉冲吸引注意力",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="text", type="text", default_value="Get Started Now",
                           description="按钮文本"),
            MotionVariable(name="url", type="text", default_value="https://example.com",
                           description="链接地址(展示用)"),
            MotionVariable(name="color", type="color", default_value="#6366F1",
                           description="按钮颜色"),
            MotionVariable(name="animation", type="text", default_value="pulse",
                           description="动画: pulse | bounce | glow"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div class="cta-wrap" style="text-align:center;opacity:0;transform:scale(0.8);">
    <div class="cta-btn" style="display:inline-block;background:{{{{color}}}};color:#fff;font-size:28px;font-weight:700;padding:24px 64px;border-radius:16px;cursor:pointer;box-shadow:0 8px 32px rgba(99,102,241,0.4);position:relative;overflow:hidden;">
      <span>{{{{text}}}}</span>
      <div class="cta-shine" style="position:absolute;top:0;left:-100%;width:100%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.2),transparent);"></div>
    </div>
    <div class="cta-url" style="margin-top:16px;font-size:16px;color:#888;opacity:0;">{{{{url}}}}</div>
  </div>
</div>''',
        "gsap_script": '''
const tl = gsap.timeline();
tl.to(".cta-wrap", {opacity:1, scale:1, duration:0.6, ease:"back.out(1.7)"})
  .to(".cta-btn", {scale:1.05, duration:0.3, yoyo:true, repeat:3, ease:"power1.inOut"})
  .to(".cta-shine", {left:"100%", duration:0.8, ease:"power1.inOut"}, "-=1.5")
  .to(".cta-url", {opacity:1, duration:0.4}, "-=1");
''',
        "default_preset": MotionPreset(
            name="signup",
            variables={"text": "Get Started Now", "url": "https://example.com",
                       "color": "#6366F1", "animation": "pulse"},
            description="注册引导 CTA",
        ),
    },

    # =======================================================================
    # 10. progress-bar — 进度条
    # =======================================================================
    {
        "id": "progress-bar",
        "name": "进度条",
        "category": "Transparent Overlay",
        "description": "动态进度条,数值从 0 填充到目标值",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="value", type="number", default_value="78",
                           description="当前值"),
            MotionVariable(name="max", type="number", default_value="100",
                           description="最大值"),
            MotionVariable(name="label", type="text", default_value="Project Completion",
                           description="进度标签"),
            MotionVariable(name="color", type="color", default_value="#22C55E",
                           description="进度条颜色"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;padding:0 120px;">
  <div class="pb-wrap" style="width:100%;opacity:0;">
    <div style="display:flex;justify-content:space-between;margin-bottom:12px;">
      <span class="pb-label" style="font-size:20px;color:#ccc;">{{{{label}}}}</span>
      <span class="pb-pct" style="font-size:20px;font-weight:700;color:{{{{color}}}};">0%</span>
    </div>
    <div style="width:100%;height:16px;background:rgba(255,255,255,0.08);border-radius:8px;overflow:hidden;">
      <div class="pb-fill" style="width:0%;height:100%;background:linear-gradient(90deg,{{{{color}}}},{{{{color}}}}cc);border-radius:8px;position:relative;">
        <div style="position:absolute;right:0;top:50%;transform:translateY(-50%);width:12px;height:12px;background:#fff;border-radius:50%;box-shadow:0 0 8px {{{{color}}}};opacity:0;" class="pb-dot"></div>
      </div>
    </div>
  </div>
</div>''',
        "gsap_script": '''
const maxV = parseInt("{{max}}", 10) || 100;
const val = parseInt("{{value}}", 10) || 0;
const pct = Math.round((val / maxV) * 100);
const pctEl = document.querySelector(".pb-pct");
const obj = {p: 0};
gsap.to(".pb-wrap", {opacity:1, duration:0.4});
gsap.timeline({delay:0.3})
  .to(".pb-fill", {width: pct + "%", duration:2, ease:"power2.out"})
  .to(".pb-dot", {opacity:1, duration:0.2}, 0.1)
  .to(obj, {p: pct, duration:2, ease:"power2.out",
    onUpdate: () => { pctEl.textContent = Math.round(obj.p) + "%"; }
  }, "<");
''',
        "default_preset": MotionPreset(
            name="completion",
            variables={"value": "78", "max": "100",
                       "label": "Project Completion", "color": "#22C55E"},
            description="项目完成度",
        ),
    },

    # =======================================================================
    # 11. notification-toast — 通知弹窗
    # =======================================================================
    {
        "id": "notification-toast",
        "name": "通知弹窗",
        "category": "Transparent Overlay",
        "description": "右上角通知弹窗,滑入显示",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="icon", type="text", default_value="✓",
                           description="图标字符"),
            MotionVariable(name="title", type="text", default_value="Payment Successful",
                           description="通知标题"),
            MotionVariable(name="message", type="text",
                           default_value="Your order #4821 has been confirmed.",
                           description="通知消息"),
            MotionVariable(name="type", type="text", default_value="success",
                           description="类型: success | error | info | warning"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:flex-start;justify-content:flex-end;padding:40px;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div class="nt-toast" style="background:rgba(20,20,30,0.9);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:24px 32px;display:flex;gap:16px;align-items:flex-start;max-width:420px;opacity:0;transform:translateX(100px);box-shadow:0 16px 48px rgba(0,0,0,0.3);">
    <div class="nt-icon" style="width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;">{{{{icon}}}}</div>
    <div>
      <div class="nt-title" style="font-size:18px;font-weight:600;color:#fff;">{{{{title}}}}</div>
      <div class="nt-msg" style="font-size:14px;color:#999;margin-top:4px;line-height:1.5;">{{{{message}}}}</div>
    </div>
  </div>
</div>
<script>
(function() {{
  const type = "{{{{type}}}}";
  const iconEl = document.querySelector(".nt-icon");
  const bg = type === "success" ? "rgba(74,222,128,0.15)"
    : type === "error" ? "rgba(248,113,113,0.15)"
    : type === "warning" ? "rgba(251,191,36,0.15)"
    : "rgba(99,102,241,0.15)";
  iconEl.style.background = bg;
}})();
</script>''',
        "gsap_script": '''
gsap.timeline()
  .to(".nt-toast", {opacity:1, x:0, duration:0.5, ease:"back.out(1.4)"})
  .from(".nt-icon", {scale:0, duration:0.3, ease:"back.out(2)"}, "-=0.2")
  .from(".nt-title", {opacity:0, y:8, duration:0.3}, "-=0.1")
  .from(".nt-msg", {opacity:0, y:8, duration:0.3}, "-=0.1");
''',
        "default_preset": MotionPreset(
            name="payment-success",
            variables={"icon": "✓", "title": "Payment Successful",
                       "message": "Your order #4821 has been confirmed.", "type": "success"},
            description="支付成功通知",
        ),
    },

    # =======================================================================
    # 12. floating-label — 浮动标签
    # =======================================================================
    {
        "id": "floating-label",
        "name": "浮动标签",
        "category": "Transparent Overlay",
        "description": "浮动标签气泡,可定位到画面任意位置",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="text", type="text", default_value="Key Insight",
                           description="标签文字"),
            MotionVariable(name="position", type="text", default_value="center",
                           description="位置: top-left | top-right | center | bottom-left | bottom-right"),
            MotionVariable(name="color", type="color", default_value="#F59E0B",
                           description="标签背景色"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;">
  <div class="fl-label" style="background:{{{{color}}}};color:#000;font-size:20px;font-weight:700;padding:14px 28px;border-radius:50px;box-shadow:0 8px 32px rgba(245,158,11,0.3);opacity:0;transform:translateY(20px);position:relative;">
    <span>{{{{text}}}}</span>
    <div class="fl-pulse" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:100%;height:100%;border-radius:50px;border:2px solid {{{{color}}}};opacity:0;"></div>
  </div>
</div>''',
        "gsap_script": '''
gsap.timeline()
  .to(".fl-label", {opacity:1, y:0, duration:0.5, ease:"back.out(1.7)"})
  .to(".fl-pulse", {opacity:0.6, scale:1.3, duration:0.6, ease:"power2.out"}, "-=0.2")
  .to(".fl-pulse", {opacity:0, scale:1.6, duration:0.6, ease:"power2.out"})
  .to(".fl-label", {scale:1.05, duration:0.3, yoyo:true, repeat:1, ease:"power1.inOut"});
''',
        "default_preset": MotionPreset(
            name="highlight",
            variables={"text": "Key Insight", "position": "center", "color": "#F59E0B"},
            description="重点标注浮动标签",
        ),
    },

    # =======================================================================
    # 13. timeline-slide — 时间线滑动
    # =======================================================================
    {
        "id": "timeline-slide",
        "name": "时间线滑动",
        "category": "Knowledge / Explainer",
        "description": "横向时间线,事件节点依次亮起展开",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="events", type="text",
                           default_value='[{"date":"2020","title":"Founded","desc":"Company established"},{"date":"2022","title":"Series A","desc":"Raised $12M funding"},{"date":"2024","title":"Global Launch","desc":"Expanded to 30 countries"},{"date":"2025","title":"IPO","desc":"Listed on NYSE"}]',
                           description="JSON array of {date,title,desc}"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px;background:#0a0a1a;font-family:'Inter',system-ui,sans-serif;">
  <div class="ts-track" style="position:relative;width:100%;display:flex;align-items:flex-start;justify-content:space-between;padding-top:60px;">
    <div class="ts-line" style="position:absolute;top:75px;left:0;right:0;height:3px;background:rgba(255,255,255,0.1);"></div>
    <div class="ts-line-fill" style="position:absolute;top:75px;left:0;height:3px;width:0%;background:linear-gradient(90deg,#6366F1,#00E5FF);"></div>
  </div>
</div>
<script>
(function() {{
  const events = {{{{events}}}};
  const track = document.querySelector(".ts-track");
  events.forEach((ev, i) => {{
    const node = document.createElement("div");
    node.className = "ts-node";
    node.style.cssText = "text-align:center;flex:1;position:relative;z-index:1;opacity:0;transform:translateY(20px);";
    node.innerHTML = '<div style="width:24px;height:24px;border-radius:50%;background:#6366F1;margin:0 auto 16px;border:3px solid #1a1a2e;position:relative;z-index:2;"></div>'
      + '<div style="font-size:16px;color:#6366F1;font-weight:700;margin-bottom:6px;">' + ev.date + '</div>'
      + '<div style="font-size:20px;color:#fff;font-weight:600;margin-bottom:4px;">' + ev.title + '</div>'
      + '<div style="font-size:14px;color:#888;">' + ev.desc + '</div>';
    track.appendChild(node);
  }});
}})();
</script>''',
        "gsap_script": '''
const nodes = gsap.utils.toArray(".ts-node");
const tl = gsap.timeline();
nodes.forEach((node, i) => {
  tl.to(node, {opacity:1, y:0, duration:0.5, ease:"power2.out"}, i * 0.4);
});
tl.to(".ts-line-fill", {width:"100%", duration: nodes.length * 0.4, ease:"power1.inOut"}, 0);
''',
        "default_preset": MotionPreset(
            name="company-milestones",
            variables={
                "events": '[{"date":"2020","title":"Founded","desc":"Company established"},{"date":"2022","title":"Series A","desc":"Raised $12M funding"},{"date":"2024","title":"Global Launch","desc":"Expanded to 30 countries"},{"date":"2025","title":"IPO","desc":"Listed on NYSE"}]',
            },
            description="公司发展里程碑",
        ),
    },

    # =======================================================================
    # 14. step-by-step — 步骤展示
    # =======================================================================
    {
        "id": "step-by-step",
        "name": "步骤展示",
        "category": "Knowledge / Explainer",
        "description": "步骤依次展示,当前步骤高亮,已完成步骤变暗",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="steps", type="text",
                           default_value='[{"num":"1","title":"Research","desc":"Gather requirements and data","icon":"🔍"},{"num":"2","title":"Design","desc":"Create architecture blueprint","icon":"📐"},{"num":"3","title":"Build","desc":"Develop and integrate","icon":"🔧"},{"num":"4","title":"Launch","desc":"Deploy to production","icon":"🚀"}]',
                           description="JSON array of {num,title,desc,icon}"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 100px;background:#0a0a1a;font-family:'Inter',system-ui,sans-serif;">
  <div class="sbs-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:32px;width:100%;"></div>
</div>
<script>
(function() {{
  const steps = {{{{steps}}}};
  const grid = document.querySelector(".sbs-grid");
  steps.forEach((s, i) => {{
    const card = document.createElement("div");
    card.className = "sbs-step";
    card.style.cssText = "background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:32px 24px;text-align:center;opacity:0;transform:translateY(30px);position:relative;overflow:hidden;";
    card.innerHTML = '<div style="font-size:40px;margin-bottom:12px;">' + s.icon + '</div>'
      + '<div style="width:36px;height:36px;border-radius:50%;background:#6366F1;color:#fff;font-size:16px;font-weight:700;display:flex;align-items:center;justify-content:center;margin:0 auto 12px;">' + s.num + '</div>'
      + '<div style="font-size:20px;font-weight:600;color:#fff;margin-bottom:6px;">' + s.title + '</div>'
      + '<div style="font-size:14px;color:#888;line-height:1.5;">' + s.desc + '</div>'
      + '<div class="sbs-bar" style="position:absolute;bottom:0;left:0;height:3px;width:0%;background:#6366F1;"></div>';
    grid.appendChild(card);
  }});
}})();
</script>''',
        "gsap_script": '''
const steps = gsap.utils.toArray(".sbs-step");
const tl = gsap.timeline();
steps.forEach((step, i) => {
  tl.to(step, {opacity:1, y:0, duration:0.5, ease:"back.out(1.4)"}, i * 0.5)
    .to(step.querySelector(".sbs-bar"), {width:"100%", duration:0.8, ease:"power2.out"}, "-=0.2")
    .to(step, {borderColor:"rgba(99,102,241,0.3)", duration:0.3}, "-=0.5");
});
''',
        "default_preset": MotionPreset(
            name="dev-process",
            variables={
                "steps": '[{"num":"1","title":"Research","desc":"Gather requirements and data","icon":"🔍"},{"num":"2","title":"Design","desc":"Create architecture blueprint","icon":"📐"},{"num":"3","title":"Build","desc":"Develop and integrate","icon":"🔧"},{"num":"4","title":"Launch","desc":"Deploy to production","icon":"🚀"}]',
            },
            description="开发流程四步走",
        ),
    },

    # =======================================================================
    # 15. comparison-split — 对比分屏
    # =======================================================================
    {
        "id": "comparison-split",
        "name": "对比分屏",
        "category": "Knowledge / Explainer",
        "description": "左右分屏对比,中间分割线动画展开",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="left_title", type="text", default_value="Before",
                           description="左侧标题"),
            MotionVariable(name="right_title", type="text", default_value="After",
                           description="右侧标题"),
            MotionVariable(name="left_items", type="text",
                           default_value='["Manual data entry","24h processing","Error-prone","High cost"]',
                           description="左侧条目 (JSON array)"),
            MotionVariable(name="right_items", type="text",
                           default_value='["Auto ingestion","Real-time","99.9% accuracy","70% savings"]',
                           description="右侧条目 (JSON array)"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;background:#0a0a1a;font-family:'Inter',system-ui,sans-serif;">
  <div class="cs-left" style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:60px 80px;opacity:0;transform:translateX(-60px);">
    <h3 style="font-size:36px;color:#F87171;margin-bottom:32px;">{{{{left_title}}}}</h3>
    <div class="cs-left-items"></div>
  </div>
  <div class="cs-divider" style="width:4px;background:linear-gradient(180deg,transparent,rgba(255,255,255,0.2),transparent);position:relative;opacity:0;">
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:48px;height:48px;border-radius:50%;background:#1a1a2e;border:2px solid rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:20px;color:#fff;">VS</div>
  </div>
  <div class="cs-right" style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:60px 80px;opacity:0;transform:translateX(60px);">
    <h3 style="font-size:36px;color:#4ADE80;margin-bottom:32px;">{{{{right_title}}}}</h3>
    <div class="cs-right-items"></div>
  </div>
</div>
<script>
(function() {{
  const left = {{{{left_items}}}};
  const right = {{{{right_items}}}};
  const lc = document.querySelector(".cs-left-items");
  const rc = document.querySelector(".cs-right-items");
  left.forEach(item => {{
    const el = document.createElement("div");
    el.style.cssText = "display:flex;align-items:center;gap:12px;margin-bottom:16px;opacity:0;";
    el.className = "cs-li";
    el.innerHTML = '<span style="color:#F87171;font-size:18px;">✗</span><span style="color:#ccc;font-size:18px;">' + item + '</span>';
    lc.appendChild(el);
  }});
  right.forEach(item => {{
    const el = document.createElement("div");
    el.style.cssText = "display:flex;align-items:center;gap:12px;margin-bottom:16px;opacity:0;";
    el.className = "cs-ri";
    el.innerHTML = '<span style="color:#4ADE80;font-size:18px;">✓</span><span style="color:#ccc;font-size:18px;">' + item + '</span>';
    rc.appendChild(el);
  }});
}})();
</script>''',
        "gsap_script": '''
gsap.timeline()
  .to(".cs-divider", {opacity:1, duration:0.4})
  .to(".cs-left", {opacity:1, x:0, duration:0.6, ease:"power2.out"}, "-=0.1")
  .to(".cs-right", {opacity:1, x:0, duration:0.6, ease:"power2.out"}, "-=0.4")
  .to(".cs-li", {opacity:1, x:0, duration:0.3, stagger:0.12, ease:"power2.out"}, "-=0.3")
  .to(".cs-ri", {opacity:1, x:0, duration:0.3, stagger:0.12, ease:"power2.out"}, "-=1.2");
''',
        "default_preset": MotionPreset(
            name="before-after",
            variables={
                "left_title": "Before",
                "right_title": "After",
                "left_items": '["Manual data entry","24h processing","Error-prone","High cost"]',
                "right_items": '["Auto ingestion","Real-time","99.9% accuracy","70% savings"]',
            },
            description="前后对比",
        ),
    },

    # =======================================================================
    # 16. definition-card — 定义卡片
    # =======================================================================
    {
        "id": "definition-card",
        "name": "定义卡片",
        "category": "Knowledge / Explainer",
        "description": "术语定义卡片,含术语/释义/示例",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="term", type="text", default_value="Neural Network",
                           description="术语"),
            MotionVariable(name="definition", type="text",
                           default_value="A computational model inspired by biological neural networks, consisting of interconnected nodes that process information using connectionist approaches.",
                           description="释义"),
            MotionVariable(name="example", type="text",
                           default_value="GPT-4 uses a transformer-based neural network with 1.8T parameters.",
                           description="示例"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:transparent;font-family:'Inter',system-ui,sans-serif;padding:0 100px;">
  <div class="dc-card" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:24px;padding:56px 64px;max-width:800px;width:100%;backdrop-filter:blur(16px);opacity:0;transform:scale(0.9);">
    <div class="dc-tag" style="display:inline-block;background:rgba(99,102,241,0.15);color:#6366F1;font-size:13px;font-weight:600;padding:6px 16px;border-radius:20px;letter-spacing:2px;text-transform:uppercase;margin-bottom:20px;opacity:0;">Definition</div>
    <h2 class="dc-term" style="font-size:48px;font-weight:800;color:#fff;margin-bottom:20px;line-height:1.2;opacity:0;">{{{{term}}}}</h2>
    <p class="dc-def" style="font-size:20px;color:#bbb;line-height:1.7;margin-bottom:28px;opacity:0;">{{{{definition}}}}</p>
    <div class="dc-example" style="background:rgba(99,102,241,0.06);border-left:3px solid #6366F1;padding:16px 24px;border-radius:0 8px 8px 0;opacity:0;">
      <div style="font-size:12px;color:#6366F1;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">Example</div>
      <div style="font-size:16px;color:#aaa;line-height:1.6;">{{{{example}}}}</div>
    </div>
  </div>
</div>''',
        "gsap_script": '''
gsap.timeline()
  .to(".dc-card", {opacity:1, scale:1, duration:0.6, ease:"back.out(1.5)"})
  .to(".dc-tag", {opacity:1, duration:0.3}, "-=0.2")
  .to(".dc-term", {opacity:1, y:0, duration:0.5, ease:"power2.out"}, "-=0.1")
  .to(".dc-def", {opacity:1, y:0, duration:0.5, ease:"power2.out"}, "-=0.2")
  .to(".dc-example", {opacity:1, x:0, duration:0.4, ease:"power2.out"}, "-=0.1");
''',
        "default_preset": MotionPreset(
            name="tech-term",
            variables={
                "term": "Neural Network",
                "definition": "A computational model inspired by biological neural networks, consisting of interconnected nodes that process information using connectionist approaches.",
                "example": "GPT-4 uses a transformer-based neural network with 1.8T parameters.",
            },
            description="技术术语定义卡",
        ),
    },

    # =======================================================================
    # 17. key-takeaway — 要点总结
    # =======================================================================
    {
        "id": "key-takeaway",
        "name": "要点总结",
        "category": "Knowledge / Explainer",
        "description": "要点依次出现,最终全部展示",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="points", type="text",
                           default_value='["AI reduces operational costs by 40%","Customer satisfaction increases by 25%","Time-to-market shortened from 6 to 2 months"]',
                           description="要点列表 (JSON array)"),
            MotionVariable(name="title", type="text", default_value="Key Takeaways",
                           description="标题"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 120px;background:#0a0a1a;font-family:'Inter',system-ui,sans-serif;">
  <h2 class="kt-title" style="font-size:42px;font-weight:800;color:#fff;margin-bottom:48px;opacity:0;">{{{{title}}}}</h2>
  <div class="kt-list" style="width:100%;display:flex;flex-direction:column;gap:24px;"></div>
</div>
<script>
(function() {{
  const points = {{{{points}}}};
  const list = document.querySelector(".kt-list");
  const colors = ["#6366F1","#00E5FF","#4ADE80","#F59E0B","#F87171"];
  points.forEach((pt, i) => {{
    const row = document.createElement("div");
    row.className = "kt-row";
    row.style.cssText = "display:flex;align-items:center;gap:20px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:24px 32px;opacity:0;transform:translateX(-40px);";
    const c = colors[i % colors.length];
    row.innerHTML = '<div style="width:10px;height:10px;border-radius:50%;background:' + c + ';flex-shrink:0;"></div>'
      + '<span style="font-size:22px;color:#ddd;line-height:1.5;">' + pt + '</span>';
    list.appendChild(row);
  }});
}})();
</script>''',
        "gsap_script": '''
gsap.timeline()
  .to(".kt-title", {opacity:1, duration:0.5, ease:"power2.out"})
  .to(".kt-row", {opacity:1, x:0, duration:0.5, stagger:0.3, ease:"power2.out"}, "-=0.1");
''',
        "default_preset": MotionPreset(
            name="summary",
            variables={
                "points": '["AI reduces operational costs by 40%","Customer satisfaction increases by 25%","Time-to-market shortened from 6 to 2 months"]',
                "title": "Key Takeaways",
            },
            description="三点要点总结",
        ),
    },

    # =======================================================================
    # 18. particle-burst — 粒子爆发
    # =======================================================================
    {
        "id": "particle-burst",
        "name": "粒子爆发",
        "category": "Transition / Effect",
        "description": "粒子从中心爆发散开,适用于转场或强调",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="count", type="number", default_value="60",
                           description="粒子数量"),
            MotionVariable(name="color", type="color", default_value="#FFD700",
                           description="粒子颜色"),
            MotionVariable(name="duration", type="number", default_value="2",
                           description="爆发持续时间(秒)"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:transparent;overflow:hidden;">
  <canvas class="pb-canvas" width="1920" height="1080" style="width:100%;height:100%;"></canvas>
</div>
<script>
(function() {{
  const canvas = document.querySelector(".pb-canvas");
  const ctx = canvas.getContext("2d");
  const count = parseInt("{{{{count}}}}", 10) || 60;
  const color = "{{{{color}}}}";
  const dur = parseFloat("{{{{duration}}}}") || 2;
  const cx = canvas.width / 2, cy = canvas.height / 2;
  const particles = [];
  for (let i = 0; i < count; i++) {{
    const angle = Math.random() * Math.PI * 2;
    const speed = 2 + Math.random() * 8;
    const size = 2 + Math.random() * 6;
    particles.push({{ x: cx, y: cy, vx: Math.cos(angle)*speed, vy: Math.sin(angle)*speed,
      size, alpha: 1, decay: 0.005 + Math.random()*0.015 }});
  }}
  window.__pb_particles = particles;
  window.__pb_ctx = ctx;
  window.__pb_color = color;
  window.__pb_cx = cx;
  window.__pb_cy = cy;
}})();
</script>''',
        "gsap_script": '''
const particles = window.__pb_particles;
const ctx = window.__pb_ctx;
const color = window.__pb_color;
const cx = window.__pb_cx, cy = window.__pb_cy;
const canvas = ctx.canvas;

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return {r,g,b};
}
const rgb = hexToRgb(color);

const proxy = {frame: 0};
gsap.to(proxy, {
  frame: 120,
  duration: parseFloat("{{duration}}") || 2,
  ease: "power2.out",
  onUpdate: () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    particles.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.05;
      p.alpha = Math.max(0, p.alpha - p.decay);
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(" + rgb.r + "," + rgb.g + "," + rgb.b + "," + p.alpha + ")";
      ctx.fill();
    });
  }
});
''',
        "default_preset": MotionPreset(
            name="golden-burst",
            variables={"count": "60", "color": "#FFD700", "duration": "2"},
            description="金色粒子爆发",
        ),
    },

    # =======================================================================
    # 19. glitch-text — 故障文字
    # =======================================================================
    {
        "id": "glitch-text",
        "name": "故障文字",
        "category": "Transition / Effect",
        "description": "赛博朋克故障风格文字,抖动 + 色彩偏移",
        "supports_transparent": True,
        "variables": [
            MotionVariable(name="text", type="text", default_value="SYSTEM ONLINE",
                           description="显示文本"),
            MotionVariable(name="intensity", type="text", default_value="high",
                           description="故障强度: low | medium | high"),
            MotionVariable(name="color", type="color", default_value="#00FF41",
                           description="主色调"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:#000;font-family:'Courier New',monospace;overflow:hidden;">
  <div class="gt-wrap" style="position:relative;text-align:center;">
    <div class="gt-text" style="font-size:80px;font-weight:900;color:{{{{color}}}};letter-spacing:8px;position:relative;">{{{{text}}}}
      <div class="gt-clone-a" style="position:absolute;top:0;left:0;width:100%;height:100%;color:#FF0040;mix-blend-mode:screen;clip-path:polygon(0 0,100% 0,100% 45%,0 45%);">{{{{text}}}}</div>
      <div class="gt-clone-b" style="position:absolute;top:0;left:0;width:100%;height:100%;color:#00E5FF;mix-blend-mode:screen;clip-path:polygon(0 55%,100% 55%,100% 100%,0 100%);">{{{{text}}}}</div>
    </div>
    <div class="gt-scanlines" style="position:absolute;top:0;left:0;width:100%;height:100%;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.15) 2px,rgba(0,0,0,0.15) 4px);pointer-events:none;"></div>
  </div>
</div>''',
        "gsap_script": '''
const intensity = "{{intensity}}" === "high" ? 20 : "{{intensity}}" === "medium" ? 10 : 5;
const tl = gsap.timeline({repeat: 4, repeatDelay: 0.1});
tl.to(".gt-clone-a", {x: -intensity, duration:0.05, ease:"steps(2)"})
  .to(".gt-clone-b", {x: intensity, duration:0.05, ease:"steps(2)"})
  .to(".gt-text", {skewX: intensity/2, duration:0.05, ease:"steps(2)"})
  .to(".gt-clone-a", {x: intensity*0.5, y:2, duration:0.05, ease:"steps(2)"})
  .to(".gt-clone-b", {x: -intensity*0.5, y:-2, duration:0.05, ease:"steps(2)"})
  .to(".gt-text", {skewX: 0, x:0, duration:0.05, ease:"steps(2)"})
  .to(".gt-clone-a", {x:0, y:0, duration:0.05})
  .to(".gt-clone-b", {x:0, y:0, duration:0.05});

gsap.to(".gt-scanlines", {y: 4, duration:0.1, repeat:-1, ease:"none"});
gsap.from(".gt-wrap", {opacity:0, scale:0.8, duration:0.3, ease:"power2.out"});
''',
        "default_preset": MotionPreset(
            name="cyber",
            variables={"text": "SYSTEM ONLINE", "intensity": "high", "color": "#00FF41"},
            description="赛博朋克故障效果",
        ),
    },

    # =======================================================================
    # 20. cinematic-bars — 电影黑边
    # =======================================================================
    {
        "id": "cinematic-bars",
        "name": "电影黑边",
        "category": "Transition / Effect",
        "description": "电影宽银幕黑边渐入,可用于开场/转场/结尾",
        "supports_transparent": False,
        "variables": [
            MotionVariable(name="aspect_ratio", type="text", default_value="2.39:1",
                           description="画面宽高比: 2.39:1 | 1.85:1 | 16:9"),
            MotionVariable(name="fade_duration", type="number", default_value="1.5",
                           description="渐入时长(秒)"),
        ],
        "html_source": f'''<div style="{_BODY_RESET}width:100%;height:100%;position:relative;background:#0a0a1a;font-family:'Inter',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;">
  <div class="cb-content" style="text-align:center;opacity:0;">
    <div style="width:80px;height:1px;background:rgba(255,255,255,0.3);margin:0 auto 24px;"></div>
    <div style="font-size:14px;color:#888;letter-spacing:6px;text-transform:uppercase;">Cinematic</div>
    <div style="font-size:56px;font-weight:200;color:#fff;letter-spacing:4px;margin-top:8px;">PRESENTATION</div>
    <div style="width:80px;height:1px;background:rgba(255,255,255,0.3);margin:24px auto 0;"></div>
  </div>
  <div class="cb-top" style="position:absolute;top:0;left:0;width:100%;height:0;background:#000;"></div>
  <div class="cb-bottom" style="position:absolute;bottom:0;left:0;width:100%;height:0;background:#000;"></div>
</div>''',
        "gsap_script": '''
const ratioStr = "{{aspect_ratio}}";
const parts = ratioStr.split(":");
const ratio = parseFloat(parts[0]) / parseFloat(parts[1]);
const containerH = 1080;
const targetBarH = Math.max(0, (containerH - containerH / ratio) / 2);
const fadeDur = parseFloat("{{fade_duration}}") || 1.5;

const tl = gsap.timeline();
tl.to(".cb-content", {opacity:1, duration: fadeDur * 0.6, ease:"power2.out"})
  .to(".cb-top", {height: targetBarH, duration: fadeDur, ease:"power2.inOut"}, 0)
  .to(".cb-bottom", {height: targetBarH, duration: fadeDur, ease:"power2.inOut"}, 0);
''',
        "default_preset": MotionPreset(
            name="widescreen",
            variables={"aspect_ratio": "2.39:1", "fade_duration": "1.5"},
            description="2.39:1 宽银幕电影黑边",
        ),
    },
]


# ---------------------------------------------------------------------------
# Catalog singleton (lazy build)
# ---------------------------------------------------------------------------

_catalog: MotionCatalog | None = None


def _build_catalog() -> MotionCatalog:
    """从 _TEMPLATE_DEFS 构建 MotionCatalog 单例。"""
    templates: list[MotionTemplate] = []
    for defn in _TEMPLATE_DEFS:
        t = MotionTemplate(
            id=defn["id"],
            name=defn["name"],
            category=defn["category"],
            description=defn["description"],
            html_source=defn["html_source"],
            gsap_script=defn["gsap_script"],
            variables=[
                v if isinstance(v, MotionVariable) else MotionVariable(**v)
                for v in defn["variables"]
            ],
            default_preset=(
                defn["default_preset"]
                if isinstance(defn["default_preset"], MotionPreset)
                else MotionPreset(**defn["default_preset"])
            ),
            supports_transparent=defn.get("supports_transparent", False),
        )
        templates.append(t)

    categories = sorted({t.category for t in templates})
    return MotionCatalog(templates=templates, categories=categories)


def get_catalog() -> MotionCatalog:
    """返回完整模板目录 (单例)。"""
    global _catalog
    if _catalog is None:
        _catalog = _build_catalog()
    return _catalog


def get_template(template_id: str) -> MotionTemplate:
    """按 ID 获取模板。

    Raises:
        KeyError: 模板不存在
    """
    cat = get_catalog()
    t = cat.get(template_id)
    if t is None:
        raise KeyError(
            f"Template '{template_id}' not found. "
            f"Available: {[t.id for t in cat.templates]}"
        )
    return t


def list_presets(template_id: str) -> list[MotionPreset]:
    """列出模板所有预设 (当前仅含 default_preset)。"""
    t = get_template(template_id)
    return [t.default_preset]


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def _substitute_vars(text: str, variables: dict[str, Any]) -> str:
    """将 ``{{var}}`` 占位符替换为变量值。"""
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        if key in variables:
            val = variables[key]
            # JSON 序列化的列表/字典直接输出原始字符串
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val)
        # 未提供的变量保留原样(让浏览器侧 JS 处理)
        return m.group(0)

    return _VAR_PATTERN.sub(_replace, text)


def _resolve_variables(
    template: MotionTemplate,
    preset_name: str | None,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """合并 default_preset → named preset → overrides。"""
    # 基础: 变量默认值
    base: dict[str, Any] = {v.name: v.default_value for v in template.variables}

    # 预设覆盖
    preset: MotionPreset | None = None
    if preset_name:
        for p in list_presets(template.id):
            if p.name == preset_name:
                preset = p
                break
        if preset is None:
            logger.warning(
                "Preset '%s' not found for template '%s', using default",
                preset_name, template.id,
            )
    else:
        preset = template.default_preset

    if preset:
        base.update(preset.variables)

    # 用户覆盖
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


async def render_motion(request: MotionRenderRequest) -> MotionRenderResult:
    """渲染动效模板为视频文件。

    流程:
        1. 解析模板 + 变量
        2. 替换 HTML / GSAP 中的占位符
        3. 调用 hyperframes_service.render_html_video 输出 MP4

    Args:
        request: 渲染请求参数

    Returns:
        MotionRenderResult
    """
    try:
        template = get_template(request.template_id)
    except KeyError as exc:
        return MotionRenderResult(
            template_id=request.template_id,
            error=str(exc),
        )

    # 变量合并
    variables = _resolve_variables(
        template, request.preset_name, request.variables,
    )

    # 占位符替换
    html_content = _substitute_vars(template.html_source, variables)
    gsap_script = _substitute_vars(template.gsap_script, variables)

    # 输出路径
    suffix = f".{request.output_format}" if request.output_format != "mp4" else ".mp4"
    output = Path("output/motion") / f"{request.template_id}{suffix}"
    output.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Rendering template '%s' (preset=%s) → %s  [%dx%d@%dfps %.1fs]",
        request.template_id, request.preset_name, output,
        request.width, request.height, request.fps, request.duration,
    )

    try:
        result = await render_html_video(
            html_content=html_content,
            output=output,
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration=request.duration,
            gsap_script=gsap_script,
        )
        return MotionRenderResult(
            output_path=result.output_path,
            template_id=request.template_id,
            preset_name=request.preset_name,
            duration=request.duration,
            success=result.success,
            error=result.error,
        )
    except Exception as exc:
        logger.exception("Render failed for template '%s'", request.template_id)
        return MotionRenderResult(
            template_id=request.template_id,
            preset_name=request.preset_name,
            duration=request.duration,
            success=False,
            error=str(exc),
        )


async def render_with_preset(
    template_id: str,
    preset_name: str,
    overrides: dict[str, Any] | None = None,
    output: str | Path | None = None,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    duration: float = 5.0,
) -> MotionRenderResult:
    """快捷渲染: 指定模板 + 预设 + 可选覆盖。

    Args:
        template_id: 模板 ID
        preset_name: 预设名称
        overrides: 变量覆盖
        output: 输出路径(可选,默认自动生成)
        width/height/fps/duration: 视频参数

    Returns:
        MotionRenderResult
    """
    req = MotionRenderRequest(
        template_id=template_id,
        preset_name=preset_name,
        variables=overrides or {},
        width=width,
        height=height,
        fps=fps,
        duration=duration,
    )
    result = await render_motion(req)

    # 如果指定了 output, 将结果移动/复制到目标位置
    if output and result.success and result.output_path:
        dest = Path(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if result.output_path != dest:
            import shutil
            shutil.copy2(str(result.output_path), str(dest))
            result.output_path = dest

    return result
