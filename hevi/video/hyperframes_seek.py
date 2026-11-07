"""HyperFrames GSAP 暂停时间轴逐帧驱动 —— oskill（纯函数，无 IO）。

页面协议（window.HF）：
- 页面加载本地 GSAP；``HF.timeline``（别名 ``tl``）是 ``paused`` 的 gsap.timeline，
  直接写 ``gsap.to(...)`` 的补间挂在已暂停的 globalTimeline 上，同样受控。
- 渲染器对第 n 帧调用 ``HF.seek(n / fps, n)``：GSAP 时间轴 totalTime(t)、Web Animations
  （CSS animation/transition）currentTime=t、所有嵌入层 ``layer.seek(t, n)``，然后截图。
- ``Math.random`` 被替换为固定种子 PRNG，确保同输入同帧。

嵌入层（EmbedLayer）：rough.js / three.js / p5 / custom，统一 ``seek(t, frame)`` 接口。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

__all__ = [
    "EmbedLayer",
    "rough_layer",
    "three_layer",
    "p5_layer",
    "custom_layer",
    "frame_times",
    "build_seek_page",
    "frame_digest",
    "sequence_digest",
    "VENDOR_FILES",
    "HF_ORIGIN",
]

HF_ORIGIN = "http://hyperframes.local"

# DEPRECATED: the window.HF protocol is a legacy shim. The converged
# seek protocol is window.__hf (see hevi/video/hf_adapter.py and
# qa.frame_adapter_contract). New code must use __hf; HF is kept only
# for compatibility with existing pages.
CONVERGED_PROTOCOL = "__hf"
HF_PROTOCOL_DEPRECATED = True

LayerKind = Literal["rough", "three", "p5", "custom"]

# 每种嵌入层需要的本地 vendor 文件（URL 路径 /vendor/<name>）
VENDOR_FILES = {
    "gsap": "gsap.min.js",
    "rough": "rough.js",
    "p5": "p5.min.js",
    "three": "three.module.js",
}


@dataclass(frozen=True)
class EmbedLayer:
    """可被暂停时间轴驱动的嵌入层。

    kind:
      - ``rough``：code 为函数体 ``(rc, ctx, t, seed, canvas, frame)``，每帧前清空画布；
        seed = base_seed + floor(frame / reseed_every)（reseed_every=0 表示不换种子）。
        请在 rough 选项里传 ``{seed}`` 以获得手绘抖动。
      - ``three``：code 为 async 函数体 ``(THREE, ctx)``，ctx={scene,camera,renderer,width,height}，
        必须 ``return function update(t, frame){...}``；渲染器每帧 update 后 renderer.render。
      - ``p5``：code 为 draw 函数体 ``(p, t, frame)``；setup 为可选 setup 函数体 ``(p)``。
        p5 实例 noLoop，seek 时 randomSeed(seed+frame) 后 redraw。
      - ``custom``：任意经典脚本，需自行 ``HF.registerLayer({seek(t, frame){...}})``。
    """

    kind: LayerKind
    id: str
    code: str
    setup: str = ""
    z: int = 1
    seed: int = 1
    reseed_every: int = 0
    style: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("rough", "three", "p5", "custom"):
            raise ValueError(f"unknown layer kind: {self.kind}")
        if not self.id or not self.id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"layer id must be [A-Za-z0-9_-]+: {self.id!r}")
        if self.reseed_every < 0:
            raise ValueError("reseed_every must be >= 0")


def rough_layer(id: str, draw_js: str, *, reseed_every: int = 0, seed: int = 1, z: int = 1, style: str = "") -> EmbedLayer:
    return EmbedLayer("rough", id, draw_js, z=z, seed=seed, reseed_every=reseed_every, style=style)


def three_layer(id: str, setup_js: str, *, z: int = 1, style: str = "") -> EmbedLayer:
    return EmbedLayer("three", id, setup_js, z=z, style=style)


def p5_layer(id: str, draw_js: str, *, setup_js: str = "", seed: int = 1, z: int = 1, style: str = "") -> EmbedLayer:
    return EmbedLayer("p5", id, draw_js, setup=setup_js, z=z, seed=seed, style=style)


def custom_layer(id: str, script_js: str, *, z: int = 1, style: str = "") -> EmbedLayer:
    return EmbedLayer("custom", id, script_js, z=z, style=style)


def frame_times(fps: int, duration: float) -> list[float]:
    """第 n 帧时间 = n / fps（不累加浮点误差）。"""
    if fps <= 0:
        raise ValueError("fps must be > 0")
    if duration <= 0:
        raise ValueError("duration must be > 0")
    n = max(1, int(round(duration * fps)))
    return [i / fps for i in range(n)]


def required_vendor(layers: Iterable[EmbedLayer], use_gsap: bool = True) -> list[str]:
    names = ["gsap"] if use_gsap else []
    for L in layers:
        if L.kind in VENDOR_FILES and L.kind not in names:
            names.append(L.kind)
    return names


_RUNTIME_JS = r"""
(function(){
  var _s = (__SEED__ >>> 0) || 1;
  Math.random = function(){ _s |= 0; _s = (_s + 0x6D2B79F5) | 0;
    var t = Math.imul(_s ^ (_s >>> 15), 1 | _s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  var layers = [], pending = [];
  var HF = window.HF = {
    fps: __FPS__, width: __W__, height: __H__, time: 0, frame: 0, timeline: null, layers: layers,
    registerLayer: function(L){ layers.push(L); return L; },
    addReady: function(p){ pending.push(p); return p; },
    _anims: function(){ return document.getAnimations ? document.getAnimations() : []; },
    whenReady: function(){
      return Promise.all(pending).then(function(){ return document.fonts ? document.fonts.ready : null; })
        .then(function(){ var a = HF._anims(); a.forEach(function(x){ try { x.pause(); } catch (e) {} });
          return Promise.all(a.map(function(x){ return x.ready.catch(function(){}); })); })
        .then(function(){ return true; });
    },
    timelineDuration: function(){
      var d = 0;
      if (HF.timeline) d = Math.max(d, HF.timeline.totalDuration());
      if (window.gsap) { gsap.globalTimeline.getChildren(false, true, true).forEach(function(c){
        if (c !== HF.timeline) d = Math.max(d, c.startTime() + c.totalDuration()); }); }
      return d;
    },
    seek: function(t, frame){
      HF.time = t; HF.frame = frame;
      if (window.gsap) {
        gsap.globalTimeline.totalTime(t, false);
        if (HF.timeline) HF.timeline.totalTime(Math.min(t, HF.timeline.totalDuration()), false);
      }
      var anims = HF._anims();
      anims.forEach(function(a){ try { a.pause(); a.currentTime = t * 1000; } catch (e) {} });
      for (var i = 0; i < layers.length; i++) layers[i].seek(t, frame);
      return Promise.all(anims.map(function(a){ return a.ready.catch(function(){}); })).then(function(){
        anims.forEach(function(a){ try { a.currentTime = t * 1000; } catch (e) {} });
        // 等两次 rAF：确保样式/合成器已提交本帧，再由渲染器截图
        return new Promise(function(r){ requestAnimationFrame(function(){ requestAnimationFrame(function(){ r(frame); }); }); });
      });
    }
  };
  if (window.gsap) {
    gsap.ticker.lagSmoothing(0);
    gsap.globalTimeline.autoRemoveChildren = false;
    gsap.globalTimeline.pause();
    HF.timeline = window.tl = gsap.timeline({paused: true});
  }
})();
"""


def _js(s: str) -> str:
    """把 Python 字符串安全嵌入 <script>。"""
    return json.dumps(s).replace("</", "<\\/")


def _layer_container(L: EmbedLayer, width: int, height: int) -> str:
    style = f"position:absolute;left:0;top:0;width:{width}px;height:{height}px;z-index:{L.z};pointer-events:none;{L.style}"
    if L.kind in ("rough", "three"):
        return (f'<div class="hf-layer" data-hf-layer="{L.kind}" style="{style}">'
                f'<canvas id="{L.id}" width="{width}" height="{height}" style="width:{width}px;height:{height}px"></canvas></div>')
    return f'<div class="hf-layer" data-hf-layer="{L.kind}" id="{L.id}" style="{style}"></div>'


def _layer_script(L: EmbedLayer, width: int, height: int) -> str:
    lid = _js(L.id)
    if L.kind == "rough":
        return f"""<script>
HF.registerLayer((function(){{
  var c = document.getElementById({lid}), ctx = c.getContext('2d'), rc = rough.canvas(c);
  var draw = function(rc, ctx, t, seed, canvas, frame){{
{L.code}
  }};
  return {{id: {lid}, kind: 'rough', seek: function(t, f){{
    ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0, 0, c.width, c.height);
    var seed = {L.seed} + ({L.reseed_every} > 0 ? Math.floor(f / {L.reseed_every}) : 0);
    draw(rc, ctx, t, seed, c, f);
  }}}};
}})());
</script>"""
    if L.kind == "three":
        return f"""<script>HF.addReady(new Promise(function(r, j){{ window['__hfReady_' + {lid}] = [r, j]; }}));</script>
<script type="module">
import * as THREE from 'three';
const done = window['__hfReady_' + {lid}];
try {{
  const c = document.getElementById({lid});
  const renderer = new THREE.WebGLRenderer({{canvas: c, antialias: false, alpha: true, preserveDrawingBuffer: true}});
  renderer.setPixelRatio(1); renderer.setSize({width}, {height}, false);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, {width} / {height}, 0.1, 1000);
  camera.position.set(0, 0, 5);
  const ctx = {{scene, camera, renderer, width: {width}, height: {height}}};
  const setup = async function(THREE, ctx){{
{L.code}
  }};
  const update = (await setup(THREE, ctx)) || function(){{}};
  HF.registerLayer({{id: {lid}, kind: 'three', seek(t, f){{ update(t, f); renderer.render(ctx.scene, ctx.camera); }}}});
  done[0]();
}} catch (e) {{ done[1](e); }}
</script>"""
    if L.kind == "p5":
        return f"""<script>
HF.addReady(new Promise(function(res, rej){{
  var userDraw = function(p, t, frame){{
{L.code}
  }};
  var userSetup = function(p){{
{L.setup}
  }};
  var inst = new p5(function(p){{
    p.setup = function(){{
      try {{ p.pixelDensity(1); p.createCanvas({width}, {height}); p.randomSeed({L.seed}); p.noiseSeed({L.seed});
        p.noLoop(); userSetup(p); res(); }} catch (e) {{ rej(e); }}
    }};
    p.draw = function(){{ userDraw(p, p.hfT || 0, p.hfF || 0); }};
  }}, document.getElementById({lid}));
  HF.registerLayer({{id: {lid}, kind: 'p5', seek: function(t, f){{
    inst.hfT = t; inst.hfF = f; inst.randomSeed({L.seed} + f); inst.redraw(); }}}});
}}));
</script>"""
    return f"<script>\n{L.code}\n</script>"


def build_seek_page(
    html_content: str,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    gsap_script: str | None = None,
    layers: Sequence[EmbedLayer] = (),
    composition_id: str = "root",
    background: str = "#000",
    seed: int = 20261022,
    vendor_base: str = "/vendor/",
) -> str:
    """生成可逐帧 seek 的完整 HTML（只引用本地 vendor，无 CDN）。

    gsap_script 里可直接用 ``tl``（paused timeline）或 ``gsap.to``。
    """
    ids = [L.id for L in layers]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate layer id")
    kinds = {L.kind for L in layers}
    head_scripts = [f'<script src="{vendor_base}{VENDOR_FILES["gsap"]}"></script>']
    if "rough" in kinds:
        head_scripts.append(f'<script src="{vendor_base}{VENDOR_FILES["rough"]}"></script>')
    if "p5" in kinds:
        head_scripts.append(f'<script src="{vendor_base}{VENDOR_FILES["p5"]}"></script>')
    if "three" in kinds:
        head_scripts.append('<script type="importmap">'
                            + json.dumps({"imports": {"three": f"{vendor_base}{VENDOR_FILES['three']}"}})
                            + "</script>")
    runtime = (_RUNTIME_JS.replace("__SEED__", str(int(seed))).replace("__FPS__", str(int(fps)))
               .replace("__W__", str(int(width))).replace("__H__", str(int(height))))
    containers = "\n".join(_layer_container(L, width, height) for L in layers)
    layer_scripts = "\n".join(_layer_script(L, width, height) for L in layers)
    user = f"<script>\n{gsap_script}\n</script>" if gsap_script else ""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {width}px; height: {height}px; overflow: hidden; background: {background}; }}
  [data-composition-id] {{ position: relative; width: 100%; height: 100%; }}
  * {{ caret-color: transparent; }}
  /* CSS 动画从一开始就暂停，只由 HF.seek 设置 currentTime（确定性） */
  *, *::before, *::after {{ animation-play-state: paused !important; }}
</style>
{chr(10).join(head_scripts)}
<script>{runtime}</script>
</head>
<body>
<div id="{composition_id}" data-composition-id="{composition_id}" data-start="0" data-width="{width}" data-height="{height}" data-fps="{fps}">
{containers}
{html_content}
</div>
{layer_scripts}
{user}
</body>
</html>
"""


def frame_digest(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def sequence_digest(digests: Sequence[str]) -> str:
    h = hashlib.sha256()
    for d in digests:
        h.update(d.encode())
    return h.hexdigest()
