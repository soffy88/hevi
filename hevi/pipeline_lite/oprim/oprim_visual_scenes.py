"""oprim:oprim_visual_scenes —— Lite 每镜程序化动画场景(SVG/CSS,零素材依赖)。

根据 cue.props.scene / title / visual_query 推断场景类型,输出自包含 HTML 片段。
录屏时只靠 CSS @keyframes,不依赖外链图/视频 —— 无 Pexels key 也能有画面。
"""

from __future__ import annotations

import html
from typing import Any

# 场景类型 → 关键词(title / visual_query / narration)
# 更具体的场景排前面;标题层匹配时「用火」优先于泛「洞穴」。
_SCENE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("fire", ("用火", "灰烬", "烧骨", "campfire", "火之争", "控火")),
    ("tools", ("石器", "砍砸", "刮削", "stone tool", "打制", "技术")),
    ("anatomy", ("体质", "脑量", "眉脊", "头骨", "evolution", "特征")),
    ("identity", ("正名", "学名", "北京种", "skull", "fossil", "定位")),
    ("dig", ("发现简史", "发掘", "安特生", "裴文中", "出土", "excavation", "1929")),
    ("timeline", ("时间", "更新世", "冰川", "测年", "ice age", "环境")),
    ("place", ("地点", "房山", "龙骨山", "地层", "limestone", "发现之地")),
    ("hunt", ("生存", "猎取", "肿骨鹿", "犀牛", "采集", "hunting")),
    ("migrate", ("演化意义", "走出", "欧亚", "定居", "migration", "意义")),
    ("lost", ("失踪", "转运", "国宝", "战乱", "crate", "下落", "1941")),
    ("close", ("收束", "记住", "火种", "从哪里来", "sunrise", "结论")),
    ("hook_cave", ("开场钩子", "钩子", "开场", "妖怪", "zhoukoudian cave")),
    ("dig", ("发现", "头盖骨")),  # 次级
]


def resolve_scene(cue_index: int, props: dict[str, Any], narration: str = "") -> str:
    """优先 props.scene;否则按 title → visual_query → narration 分层推断。

    标题优先,避免旁白里随口提到的「洞穴/火」把专用场景盖掉。
    """
    explicit = str(props.get("scene") or props.get("visual") or "").strip().lower()
    # 允许强制指定;但自动推断时忽略上次残留的 scene 字段 —— 调用方应清掉再推断。
    if explicit and explicit in _SCENE_BUILDERS and props.get("_scene_locked"):
        return explicit

    layers = [
        str(props.get("title") or ""),
        str(props.get("visual_query") or ""),
        str(props.get("eyebrow") or ""),
        (narration or "")[:60],
    ]
    for layer in layers:
        blob = layer.lower()
        if not blob.strip():
            continue
        for scene_id, kws in _SCENE_KEYWORDS:
            if any(k.lower() in blob for k in kws):
                return scene_id
    cycle = ("hook_cave", "timeline", "tools", "fire", "migrate", "close")
    return cycle[cue_index % len(cycle)]


def build_visual_html(scene: str, *, title: str = "") -> str:
    """返回 .viz 容器内 HTML(已 escape title 仅用于个别场景标注)。"""
    builder = _SCENE_BUILDERS.get(scene) or _SCENE_BUILDERS["default"]
    return builder(html.escape(title) if title else "")


def _s(title: str) -> str:
    return ""


def _viz_hook_cave(_: str) -> str:
    return """
<div class="viz viz-cave">
  <div class="sky"></div>
  <div class="mountain m1"></div>
  <div class="mountain m2"></div>
  <div class="cave-mouth"></div>
  <div class="silhouette"></div>
  <div class="stars"></div>
</div>"""


def _viz_identity(_: str) -> str:
    return """
<div class="viz viz-skull">
  <svg viewBox="0 0 200 220" class="skull-svg">
    <ellipse class="cranium" cx="100" cy="90" rx="62" ry="70"/>
    <path class="brow" d="M45 95 Q100 120 155 95"/>
    <ellipse class="eye l" cx="75" cy="100" rx="12" ry="16"/>
    <ellipse class="eye r" cx="125" cy="100" rx="12" ry="16"/>
    <path class="jaw" d="M60 140 Q100 185 140 140"/>
    <text x="100" y="210" text-anchor="middle" class="label">直立人 · 北京种</text>
  </svg>
  <div class="orbit o1"></div>
  <div class="orbit o2"></div>
</div>"""


def _viz_timeline(_: str) -> str:
    return """
<div class="viz viz-timeline">
  <div class="axis"></div>
  <div class="tick t1"><span>70万</span></div>
  <div class="tick t2"><span>40万</span></div>
  <div class="tick t3"><span>20万</span></div>
  <div class="ice-wave"></div>
  <div class="marker"></div>
</div>"""


def _viz_place(_: str) -> str:
    return """
<div class="viz viz-place">
  <div class="strata s1"></div>
  <div class="strata s2"></div>
  <div class="strata s3"></div>
  <div class="strata s4"></div>
  <div class="bone b1"></div>
  <div class="bone b2"></div>
  <div class="label-float">龙骨山地层</div>
</div>"""


def _viz_dig(_: str) -> str:
    return """
<div class="viz viz-dig">
  <div class="grid"></div>
  <div class="brush"></div>
  <div class="find"></div>
  <div class="year-badge">1929</div>
  <div class="spark s1"></div>
  <div class="spark s2"></div>
  <div class="spark s3"></div>
</div>"""


def _viz_anatomy(_: str) -> str:
    return """
<div class="viz viz-anatomy">
  <div class="compare">
    <div class="head ape"><span>猿</span></div>
    <div class="arrow">→</div>
    <div class="head peking"><span>北京猿人</span></div>
    <div class="arrow">→</div>
    <div class="head modern"><span>现代人</span></div>
  </div>
  <div class="brain-bar"><i style="--w:55%"></i><span>脑量 ~1000ml</span></div>
</div>"""


def _viz_tools(_: str) -> str:
    return """
<div class="viz viz-tools">
  <div class="tool chopper"></div>
  <div class="tool scraper"></div>
  <div class="tool point"></div>
  <div class="chips c1"></div>
  <div class="chips c2"></div>
  <div class="chips c3"></div>
  <div class="hand-hit"></div>
</div>"""


def _viz_fire(_: str) -> str:
    return """
<div class="viz viz-fire">
  <div class="embers"></div>
  <div class="flame f1"></div>
  <div class="flame f2"></div>
  <div class="flame f3"></div>
  <div class="log"></div>
  <div class="ash-layer"></div>
  <div class="question">人为控火 ? 自然野火 ?</div>
</div>"""


def _viz_hunt(_: str) -> str:
    return """
<div class="viz viz-hunt">
  <div class="ground"></div>
  <div class="deer"></div>
  <div class="hunter"></div>
  <div class="track tr1"></div>
  <div class="track tr2"></div>
  <div class="track tr3"></div>
</div>"""


def _viz_migrate(_: str) -> str:
    return """
<div class="viz viz-migrate">
  <div class="globe"></div>
  <div class="path"></div>
  <div class="dot africa"></div>
  <div class="dot eurasia"></div>
  <div class="dot beijing"></div>
  <div class="pulse"></div>
</div>"""


def _viz_lost(_: str) -> str:
    return """
<div class="viz viz-lost">
  <div class="crate"></div>
  <div class="stamp">MISSING</div>
  <div class="fog"></div>
  <div class="year">1941</div>
</div>"""


def _viz_close(_: str) -> str:
    return """
<div class="viz viz-close">
  <div class="sun"></div>
  <div class="rays"></div>
  <div class="ridge"></div>
  <div class="spark-line"></div>
  <div class="ember-rise e1"></div>
  <div class="ember-rise e2"></div>
  <div class="ember-rise e3"></div>
</div>"""


def _viz_default(_: str) -> str:
    return """
<div class="viz viz-default">
  <div class="ring r1"></div>
  <div class="ring r2"></div>
  <div class="ring r3"></div>
  <div class="core"></div>
</div>"""


_SCENE_BUILDERS = {
    "hook_cave": _viz_hook_cave,
    "identity": _viz_identity,
    "timeline": _viz_timeline,
    "place": _viz_place,
    "dig": _viz_dig,
    "anatomy": _viz_anatomy,
    "tools": _viz_tools,
    "fire": _viz_fire,
    "hunt": _viz_hunt,
    "migrate": _viz_migrate,
    "lost": _viz_lost,
    "close": _viz_close,
    "default": _viz_default,
}


# 所有场景共用的 CSS(注入到主模板)
VISUAL_CSS = """
  /* ── 视觉层布局 ── */
  .slide { justify-content: flex-start; padding: 36px 36px 48px; gap: 0; }
  .viz {
    position: relative; width: 88%; height: 42%; margin: 28px auto 18px;
    border-radius: 24px; overflow: hidden;
    background: linear-gradient(160deg, #1a2238 0%, #0d111c 100%);
    box-shadow: 0 20px 50px rgba(0,0,0,.45), inset 0 0 0 1px rgba(125,211,252,.12);
  }
  .slide.is-active .viz { animation: vizIn .7s cubic-bezier(.2,.8,.2,1) both; }
  @keyframes vizIn {
    from { opacity: 0; transform: scale(.92) translateY(18px); }
    to { opacity: 1; transform: scale(1) translateY(0); }
  }
  .eyebrow { margin-top: 4px; margin-bottom: 10px; font-size: 18px; }
  .title { font-size: 36px; max-width: 90%; }
  .narration { margin-top: 16px; font-size: 20px; max-width: 90%; color: #cbd5e1; }

  /* cave */
  .viz-cave .sky {
    position:absolute; inset:0;
    background: linear-gradient(180deg,#1e293b 0%,#0f172a 55%,#1c1917 100%);
  }
  .viz-cave .mountain {
    position:absolute; bottom:18%; width:70%; height:45%;
    background:#334155; border-radius:50% 50% 0 0; filter:blur(0.5px);
  }
  .viz-cave .m1 { left:-10%; animation: drift 8s ease-in-out infinite alternate; }
  .viz-cave .m2 { right:-15%; background:#1e293b; height:55%; animation: drift 10s ease-in-out infinite alternate-reverse; }
  .viz-cave .cave-mouth {
    position:absolute; left:50%; bottom:8%; transform:translateX(-50%);
    width:38%; height:42%; background:#020617; border-radius:50% 50% 8% 8%;
    box-shadow: inset 0 -20px 40px rgba(56,189,248,.15);
  }
  .viz-cave .silhouette {
    position:absolute; left:50%; bottom:14%; transform:translateX(-50%);
    width:14%; height:22%; background:#0f172a; border-radius:40% 40% 20% 20%;
    animation: breathe 2.4s ease-in-out infinite;
  }
  .viz-cave .stars {
    position:absolute; inset:0;
    background-image: radial-gradient(1.5px 1.5px at 20% 30%, #fff, transparent),
      radial-gradient(1px 1px at 70% 20%, #bae6fd, transparent),
      radial-gradient(1.2px 1.2px at 40% 50%, #fff, transparent),
      radial-gradient(1px 1px at 85% 40%, #e0f2fe, transparent);
    animation: twinkle 3s ease-in-out infinite;
  }
  @keyframes drift { from { transform: translateX(0); } to { transform: translateX(12px); } }
  @keyframes breathe { 0%,100%{ transform:translateX(-50%) scaleY(1);} 50%{ transform:translateX(-50%) scaleY(1.06);} }
  @keyframes twinkle { 0%,100%{opacity:.7;} 50%{opacity:1;} }

  /* skull */
  .viz-skull { display:flex; align-items:center; justify-content:center; }
  .skull-svg { width:55%; height:85%; z-index:2; animation: floatY 3.5s ease-in-out infinite; }
  .skull-svg .cranium { fill:#e2e8f0; stroke:#94a3b8; stroke-width:2; }
  .skull-svg .brow { fill:none; stroke:#64748b; stroke-width:8; stroke-linecap:round; }
  .skull-svg .eye { fill:#0f172a; }
  .skull-svg .jaw { fill:#cbd5e1; stroke:#94a3b8; stroke-width:2; }
  .skull-svg .label { fill:#7dd3fc; font-size:12px; font-family:system-ui,sans-serif; }
  .viz-skull .orbit {
    position:absolute; border:1px dashed rgba(125,211,252,.35); border-radius:50%;
    animation: spin 12s linear infinite;
  }
  .viz-skull .o1 { width:70%; height:70%; }
  .viz-skull .o2 { width:85%; height:85%; animation-direction:reverse; animation-duration:18s; }
  @keyframes floatY { 0%,100%{transform:translateY(0);} 50%{transform:translateY(-10px);} }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* timeline */
  .viz-timeline { display:flex; align-items:center; justify-content:center; }
  .viz-timeline .axis {
    position:absolute; left:10%; right:10%; top:48%; height:4px;
    background:linear-gradient(90deg,#38bdf8,#a78bfa); border-radius:2px;
  }
  .viz-timeline .tick {
    position:absolute; top:42%; width:12px; height:12px; border-radius:50%;
    background:#38bdf8; box-shadow:0 0 12px #38bdf8;
  }
  .viz-timeline .tick span {
    position:absolute; top:18px; left:50%; transform:translateX(-50%);
    font-size:14px; color:#94a3b8; white-space:nowrap;
  }
  .viz-timeline .t1 { left:18%; animation: pop .6s .1s both; }
  .viz-timeline .t2 { left:48%; animation: pop .6s .35s both; }
  .viz-timeline .t3 { left:78%; animation: pop .6s .6s both; }
  .viz-timeline .marker {
    position:absolute; top:30%; left:18%; width:16px; height:16px;
    background:#fbbf24; border-radius:50%; box-shadow:0 0 16px #fbbf24;
    animation: slideMark 4s ease-in-out infinite alternate;
  }
  .viz-timeline .ice-wave {
    position:absolute; bottom:0; left:0; right:0; height:28%;
    background:linear-gradient(180deg,transparent,rgba(56,189,248,.2));
    animation: wave 3s ease-in-out infinite;
  }
  @keyframes pop { from{transform:scale(0);opacity:0;} to{transform:scale(1);opacity:1;} }
  @keyframes slideMark { from{left:18%;} to{left:78%;} }
  @keyframes wave { 0%,100%{transform:translateY(0);} 50%{transform:translateY(-6px);} }

  /* place strata */
  .viz-place .strata { position:absolute; left:0; right:0; height:22%; }
  .viz-place .s1 { top:10%; background:#44403c; animation: shift 6s linear infinite; }
  .viz-place .s2 { top:32%; background:#57534e; animation: shift 7s linear infinite reverse; }
  .viz-place .s3 { top:54%; background:#292524; animation: shift 8s linear infinite; }
  .viz-place .s4 { top:76%; background:#1c1917; }
  .viz-place .bone {
    position:absolute; width:40px; height:12px; background:#e7e5e4; border-radius:6px;
    transform:rotate(-20deg); box-shadow:0 0 8px rgba(255,255,255,.3);
  }
  .viz-place .b1 { top:38%; left:30%; animation: glow 2s ease-in-out infinite; }
  .viz-place .b2 { top:60%; left:55%; transform:rotate(15deg); animation: glow 2.4s ease-in-out infinite .4s; }
  .viz-place .label-float {
    position:absolute; top:12px; right:16px; color:#fbbf24; font-size:16px; font-weight:700;
    letter-spacing:2px;
  }
  @keyframes shift { from{background-position:0 0;} to{background-position:40px 0;} }
  @keyframes glow { 0%,100%{opacity:.7;} 50%{opacity:1; box-shadow:0 0 16px #fde68a;} }

  /* dig */
  .viz-dig .grid {
    position:absolute; inset:12%;
    background-image: linear-gradient(rgba(148,163,184,.2) 1px, transparent 1px),
      linear-gradient(90deg, rgba(148,163,184,.2) 1px, transparent 1px);
    background-size: 40px 40px;
  }
  .viz-dig .find {
    position:absolute; left:42%; top:40%; width:56px; height:48px;
    background:#e2e8f0; border-radius:50% 50% 40% 40%;
    box-shadow:0 0 24px rgba(251,191,36,.6);
    animation: reveal 1.2s ease both;
  }
  .viz-dig .brush {
    position:absolute; width:8px; height:70px; background:#a8a29e; border-radius:4px;
    left:55%; top:20%; transform-origin:bottom center;
    animation: brush 1.6s ease-in-out infinite;
  }
  .viz-dig .year-badge {
    position:absolute; top:16px; left:16px; padding:6px 14px; border-radius:999px;
    background:rgba(251,191,36,.2); color:#fbbf24; font-weight:800; font-size:22px;
    animation: pop .5s .8s both;
  }
  .viz-dig .spark {
    position:absolute; width:6px; height:6px; border-radius:50%; background:#fde68a;
    animation: spark 1.2s ease-out infinite;
  }
  .viz-dig .s1 { left:48%; top:38%; animation-delay:.1s; }
  .viz-dig .s2 { left:55%; top:42%; animation-delay:.3s; }
  .viz-dig .s3 { left:50%; top:48%; animation-delay:.5s; }
  @keyframes reveal { from{transform:scale(0);opacity:0;} to{transform:scale(1);opacity:1;} }
  @keyframes brush { 0%,100%{transform:rotate(-25deg);} 50%{transform:rotate(20deg);} }
  @keyframes spark { from{opacity:1; transform:translate(0,0) scale(1);} to{opacity:0; transform:translate(20px,-30px) scale(.2);} }

  /* anatomy */
  .viz-anatomy { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:28px; }
  .viz-anatomy .compare { display:flex; align-items:flex-end; gap:14px; }
  .viz-anatomy .head {
    width:70px; border-radius:40% 40% 30% 30%; background:#94a3b8;
    display:flex; align-items:flex-end; justify-content:center; padding-bottom:8px;
    color:#0f172a; font-size:12px; font-weight:800;
  }
  .viz-anatomy .ape { height:70px; background:#78716c; animation: pop .5s both; }
  .viz-anatomy .peking { height:90px; background:#e2e8f0; box-shadow:0 0 20px #38bdf8; animation: pop .5s .2s both; }
  .viz-anatomy .modern { height:100px; background:#f8fafc; animation: pop .5s .4s both; }
  .viz-anatomy .arrow { color:#64748b; font-size:22px; margin-bottom:30px; }
  .viz-anatomy .brain-bar {
    width:70%; height:18px; background:#1e293b; border-radius:9px; position:relative; overflow:hidden;
  }
  .viz-anatomy .brain-bar i {
    display:block; height:100%; width:var(--w); background:linear-gradient(90deg,#38bdf8,#a78bfa);
    border-radius:9px; animation: fillBar 1.4s ease both;
  }
  .viz-anatomy .brain-bar span {
    position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
    font-size:12px; color:#fff; font-weight:700;
  }
  @keyframes fillBar { from{width:0;} }

  /* tools */
  .viz-tools { display:flex; align-items:center; justify-content:center; gap:28px; }
  .viz-tools .tool {
    width:70px; height:90px; background:#a8a29e; position:relative;
    clip-path: polygon(30% 0, 80% 15%, 70% 100%, 20% 90%);
    animation: toolHit .9s ease-in-out infinite;
  }
  .viz-tools .scraper { clip-path: polygon(10% 20%, 90% 0, 85% 100%, 20% 80%); animation-delay:.15s; background:#78716c; }
  .viz-tools .point { clip-path: polygon(50% 0, 80% 100%, 20% 100%); animation-delay:.3s; background:#d6d3d1; width:50px; }
  .viz-tools .chips {
    position:absolute; width:10px; height:10px; background:#e7e5e4; border-radius:2px;
    animation: chip 1s ease-out infinite;
  }
  .viz-tools .c1 { left:30%; top:40%; }
  .viz-tools .c2 { left:50%; top:35%; animation-delay:.2s; }
  .viz-tools .c3 { left:65%; top:45%; animation-delay:.4s; }
  .viz-tools .hand-hit {
    position:absolute; bottom:18%; left:20%; width:40px; height:40px; border-radius:50%;
    border:3px solid rgba(251,191,36,.5); animation: pulseRing 1.2s ease-out infinite;
  }
  @keyframes toolHit { 0%,100%{transform:rotate(0) translateY(0);} 40%{transform:rotate(-8deg) translateY(6px);} 60%{transform:rotate(6deg);} }
  @keyframes chip { from{opacity:1; transform:translate(0,0);} to{opacity:0; transform:translate(30px,40px) rotate(40deg);} }
  @keyframes pulseRing { from{transform:scale(.6);opacity:1;} to{transform:scale(1.8);opacity:0;} }

  /* fire */
  .viz-fire { display:flex; align-items:flex-end; justify-content:center; }
  .viz-fire .log {
    position:absolute; bottom:22%; width:40%; height:14px; background:#44403c; border-radius:8px;
  }
  .viz-fire .flame {
    position:absolute; bottom:28%; width:28px; border-radius:50% 50% 20% 20%;
    animation: flicker .4s ease-in-out infinite alternate;
  }
  .viz-fire .f1 { height:70px; background:linear-gradient(#fbbf24,#ef4444); left:46%; animation-delay:0s; }
  .viz-fire .f2 { height:90px; width:36px; background:linear-gradient(#fde68a,#f97316); left:50%; animation-delay:.1s; }
  .viz-fire .f3 { height:60px; background:linear-gradient(#fdba74,#dc2626); left:55%; animation-delay:.2s; }
  .viz-fire .embers {
    position:absolute; inset:0;
    background-image: radial-gradient(2px 2px at 40% 50%, #fbbf24, transparent),
      radial-gradient(2px 2px at 60% 40%, #f97316, transparent);
    animation: riseEmber 2s linear infinite;
  }
  .viz-fire .ash-layer {
    position:absolute; bottom:0; left:0; right:0; height:18%;
    background:linear-gradient(transparent, rgba(120,113,108,.5));
  }
  .viz-fire .question {
    position:absolute; top:16px; width:100%; text-align:center;
    color:#fde68a; font-size:18px; font-weight:700; letter-spacing:1px;
    animation: blink 2s ease-in-out infinite;
  }
  @keyframes flicker { from{transform:scaleY(1) scaleX(1);} to{transform:scaleY(1.12) scaleX(.92);} }
  @keyframes riseEmber { from{transform:translateY(20px);opacity:1;} to{transform:translateY(-40px);opacity:0;} }
  @keyframes blink { 0%,100%{opacity:.5;} 50%{opacity:1;} }

  /* hunt */
  .viz-hunt .ground {
    position:absolute; bottom:0; left:0; right:0; height:30%;
    background:linear-gradient(180deg,#365314,#1a2e05);
  }
  .viz-hunt .deer {
    position:absolute; bottom:28%; right:18%; width:80px; height:50px;
    background:#a8a29e; border-radius:30px 40px 10px 20px;
    animation: run 2.5s ease-in-out infinite alternate;
  }
  .viz-hunt .deer::before {
    content:""; position:absolute; left:8px; top:-18px; width:6px; height:28px;
    background:#a8a29e; transform:rotate(-20deg); box-shadow:14px 4px 0 #a8a29e;
  }
  .viz-hunt .hunter {
    position:absolute; bottom:28%; left:20%; width:28px; height:55px;
    background:#1e293b; border-radius:8px 8px 4px 4px;
    animation: stalk 2.5s ease-in-out infinite alternate;
  }
  .viz-hunt .track {
    position:absolute; bottom:22%; width:14px; height:8px; background:rgba(0,0,0,.25); border-radius:50%;
  }
  .viz-hunt .tr1 { left:40%; }
  .viz-hunt .tr2 { left:50%; }
  .viz-hunt .tr3 { left:60%; }
  @keyframes run { from{transform:translateX(0);} to{transform:translateX(-30px);} }
  @keyframes stalk { from{transform:translateX(0);} to{transform:translateX(20px);} }

  /* migrate */
  .viz-migrate { display:flex; align-items:center; justify-content:center; }
  .viz-migrate .globe {
    width:55%; height:70%; border-radius:50%;
    background:radial-gradient(circle at 35% 35%, #38bdf8 0%, #1e3a5f 45%, #0f172a 100%);
    box-shadow:0 0 40px rgba(56,189,248,.3); animation: spin 20s linear infinite;
  }
  .viz-migrate .dot {
    position:absolute; width:12px; height:12px; border-radius:50%; background:#fbbf24;
    box-shadow:0 0 12px #fbbf24;
  }
  .viz-migrate .africa { left:38%; top:55%; }
  .viz-migrate .eurasia { left:52%; top:38%; animation: pop .5s .4s both; }
  .viz-migrate .beijing { left:68%; top:42%; background:#f43f5e; box-shadow:0 0 16px #f43f5e; animation: pop .5s .8s both; }
  .viz-migrate .path {
    position:absolute; left:40%; top:48%; width:28%; height:3px;
    background:linear-gradient(90deg,#fbbf24,#f43f5e); transform:rotate(-12deg);
    transform-origin:left center; animation: grow 1.5s ease both;
  }
  .viz-migrate .pulse {
    position:absolute; left:68%; top:42%; width:12px; height:12px; border-radius:50%;
    border:2px solid #f43f5e; animation: pulseRing 1.5s ease-out infinite;
  }
  @keyframes grow { from{transform:rotate(-12deg) scaleX(0);} to{transform:rotate(-12deg) scaleX(1);} }

  /* lost */
  .viz-lost { display:flex; align-items:center; justify-content:center; background:linear-gradient(160deg,#1c1917,#0c0a09)!important; }
  .viz-lost .crate {
    width:42%; height:38%; background:#78350f; border:4px solid #92400e;
    box-shadow:8px 12px 0 #451a03; animation: shake 2.5s ease-in-out infinite;
  }
  .viz-lost .stamp {
    position:absolute; color:#ef4444; font-size:36px; font-weight:900;
    border:4px solid #ef4444; padding:8px 16px; transform:rotate(-18deg);
    letter-spacing:4px; animation: stampIn .6s .5s both;
  }
  .viz-lost .fog {
    position:absolute; inset:0; background:radial-gradient(transparent 30%, rgba(0,0,0,.7));
    animation: fogPulse 3s ease-in-out infinite;
  }
  .viz-lost .year {
    position:absolute; bottom:16px; color:#a8a29e; font-size:20px; font-weight:700; letter-spacing:6px;
  }
  @keyframes shake { 0%,100%{transform:translateX(0);} 20%{transform:translateX(-4px) rotate(-1deg);} 40%{transform:translateX(4px);} }
  @keyframes stampIn { from{opacity:0; transform:rotate(-18deg) scale(2);} to{opacity:1; transform:rotate(-18deg) scale(1);} }
  @keyframes fogPulse { 0%,100%{opacity:.6;} 50%{opacity:1;} }

  /* close */
  .viz-close { background:linear-gradient(180deg,#0c4a6e 0%,#0f172a 55%,#1c1917 100%)!important; }
  .viz-close .sun {
    position:absolute; left:50%; top:28%; transform:translateX(-50%);
    width:70px; height:70px; border-radius:50%;
    background:radial-gradient(#fde68a,#f59e0b); box-shadow:0 0 40px #fbbf24;
    animation: sunRise 2s ease both;
  }
  .viz-close .rays {
    position:absolute; left:50%; top:28%; width:140px; height:140px; transform:translate(-50%,-25%);
    background:conic-gradient(from 0deg, transparent, rgba(251,191,36,.25), transparent 30%);
    animation: spin 8s linear infinite;
  }
  .viz-close .ridge {
    position:absolute; bottom:0; left:0; right:0; height:35%;
    background:#1e293b; clip-path:polygon(0 60%, 20% 30%, 40% 55%, 60% 20%, 80% 45%, 100% 25%, 100% 100%, 0 100%);
  }
  .viz-close .ember-rise {
    position:absolute; bottom:30%; width:6px; height:6px; border-radius:50%; background:#fbbf24;
    animation: riseUp 2.5s ease-out infinite;
  }
  .viz-close .e1 { left:40%; animation-delay:0s; }
  .viz-close .e2 { left:50%; animation-delay:.5s; background:#f97316; }
  .viz-close .e3 { left:60%; animation-delay:1s; }
  @keyframes sunRise { from{transform:translateX(-50%) translateY(40px);opacity:0;} to{transform:translateX(-50%) translateY(0);opacity:1;} }
  @keyframes riseUp { from{transform:translateY(0);opacity:1;} to{transform:translateY(-80px);opacity:0;} }

  /* default */
  .viz-default { display:flex; align-items:center; justify-content:center; }
  .viz-default .ring {
    position:absolute; border:2px solid rgba(56,189,248,.35); border-radius:50%;
    animation: pulseRing 2.5s ease-out infinite;
  }
  .viz-default .r1 { width:30%; height:40%; }
  .viz-default .r2 { width:50%; height:60%; animation-delay:.4s; }
  .viz-default .r3 { width:70%; height:80%; animation-delay:.8s; }
  .viz-default .core {
    width:48px; height:48px; border-radius:50%;
    background:radial-gradient(#7dd3fc,#2563eb); box-shadow:0 0 30px #38bdf8;
    animation: breathe 2s ease-in-out infinite;
  }
"""


def assign_scenes_to_cues(cues: list[Any]) -> list[str]:
    """给一组 cue 解析场景 id 列表(测试/调试用)。"""
    out: list[str] = []
    for c in cues:
        props = getattr(c, "props", None) or {}
        if isinstance(c, dict):
            props = c.get("props") or {}
            narr = str(c.get("narration") or "")
            idx = int(c.get("index") or 0)
        else:
            narr = str(getattr(c, "narration", "") or "")
            idx = int(getattr(c, "index", 0) or 0)
        out.append(resolve_scene(idx, dict(props), narr))
    return out


__all__ = [
    "VISUAL_CSS",
    "assign_scenes_to_cues",
    "build_visual_html",
    "resolve_scene",
]
