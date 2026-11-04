"""Three.js imaging upgrade (``world.threejs_imaging_upgrade``).

Clean-room minimal imaging upgrade for the three.js scene
discipline described in ``hevi-vs-open-3d-skills.md`` section
2.1: three linked lighting presets, a post-processing stack, a
caller-supplied performance budget, three quality tiers that
never downgrade while recording, named vantages, and arc
flights. Every line of scene code here is newly written. It
reuses only hevi's own pieces: the vendored Three.js r169
module and its vendored post-processing passes, the analytic
heightfield constants of ``video.athenaion_world_engine``
(``HEIGHT_CONSTANTS``), the Playwright Chromium + SwiftShader
harness pattern, and the ``__hf`` settle protocol. Nothing is
downloaded.

Post-processing honesty: the vendored passes in this
repository are RenderPass, UnrealBloomPass and OutputPass.
There is no vendored GTAO pass, so the applied stack is
RenderPass -> UnrealBloomPass -> OutputPass and the report
records ``gtao_applied: false`` with the reason, even when the
caller declares GTAO parameters. The GTAO slot stays in the
plan vocabulary (parameters caller-supplied, never defaulted)
so a future vendored pass can fill it without changing the
plan shape -- but until then GTAO is declared, not applied,
and no screenshot in this module claims otherwise.

Threshold discipline: lighting values, bloom values, quality
tier values and the performance budget are all supplied by
the caller. This module has no default exposure, bloom
strength, frame-time, draw-call or triangle budget, and no
author-reported number is used as a threshold. Frame time is
not claimed: the report records seek-plus-screenshot time
labelled as such, and the frame-time budget item is
``not_checked`` because a screenshot path cannot measure pure
frame time. Draw calls and triangles are read from the real
renderer info of a direct render of the same scene and camera
immediately before the composer pass (the composer's own
passes reset the renderer info, so reading it after the
composer would report only the final quad) and compared with
the caller-supplied budget.

Determinism is measured: the preset and flight shots are
captured twice in fresh browsers and the per-shot PNG hashes
must match exactly. A missing Playwright/Chromium or vendored
Three.js module raises :class:`CapabilityError`.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hevi.capabilities.athenaion_browser import (
    CHROMIUM_ARGS,
    resolve_three_module,
    three_revision,
)
from hevi.capabilities.pure_helpers import (
    HEIGHT_CONSTANTS,
)
from hevi.capabilities.deterministic_render_gate import check_render_plan
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.frame_adapter_contract import check_adapter_plan
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PRESET_NAMES = ("morning", "golden", "night")
QUALITY_TIERS = ("low", "balanced", "high")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_PRESET_NUMBERS = (
    "sun_elevation_deg", "sun_azimuth_deg", "sun_intensity",
    "hemisphere_intensity", "fog_density", "exposure",
)
_PRESET_COLORS = (
    "sky_horizon", "sky_zenith", "sun_color",
    "hemisphere_sky", "hemisphere_ground", "fog_color",
)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def validate_upgrade_plan(plan: Any) -> dict[str, Any]:
    """Judge an imaging-upgrade plan. Caller supplies all values."""
    if not isinstance(plan, dict):
        raise CapabilityError(
            "world.threejs_imaging_upgrade: plan must be a JSON object"
        )
    issues: list[dict[str, Any]] = []
    upgrade = plan.get("upgrade")
    if not isinstance(upgrade, dict):
        raise CapabilityError(
            "world.threejs_imaging_upgrade: plan requires an 'upgrade' object"
        )

    presets = upgrade.get("presets")
    if not isinstance(presets, dict):
        issues.append(_issue("presets_missing", "upgrade must carry a 'presets' object"))
        presets = {}
    for name in PRESET_NAMES:
        preset = presets.get(name)
        if not isinstance(preset, dict):
            issues.append(
                _issue("preset_missing", f"preset {name!r} must be declared with caller-supplied values",
                       preset=name)
            )
            continue
        for field in _PRESET_NUMBERS:
            if not _is_num(preset.get(field)):
                issues.append(
                    _issue("preset_value_missing",
                           f"preset {name!r} must supply numeric {field!r}; no default is used",
                           preset=name, field=field)
                )
        for field in _PRESET_COLORS:
            value = preset.get(field)
            if not isinstance(value, str) or not _HEX_RE.match(value.strip()):
                issues.append(
                    _issue("preset_color_missing",
                           f"preset {name!r} must supply {field!r} as #RRGGBB",
                           preset=name, field=field)
                )

    quality_params = upgrade.get("quality_params")
    if not isinstance(quality_params, dict):
        issues.append(_issue("quality_params_missing", "upgrade must carry 'quality_params'"))
        quality_params = {}
    for tier in QUALITY_TIERS:
        tier_params = quality_params.get(tier)
        if not isinstance(tier_params, dict):
            issues.append(
                _issue("quality_tier_missing", f"quality tier {tier!r} must be declared", tier=tier)
            )
            continue
        segments = tier_params.get("terrain_segments")
        if not isinstance(segments, int) or isinstance(segments, bool) or segments <= 0:
            issues.append(
                _issue("quality_value_missing",
                       f"quality tier {tier!r} must supply positive integer 'terrain_segments'",
                       tier=tier)
            )
        shadow = tier_params.get("shadow_map_size")
        if not isinstance(shadow, int) or isinstance(shadow, bool) or shadow <= 0:
            issues.append(
                _issue("quality_value_missing",
                       f"quality tier {tier!r} must supply positive integer 'shadow_map_size'",
                       tier=tier)
            )
        cap = tier_params.get("pixel_ratio_cap")
        if not _is_num(cap) or float(cap) <= 0:
            issues.append(
                _issue("quality_value_missing",
                       f"quality tier {tier!r} must supply positive numeric 'pixel_ratio_cap'",
                       tier=tier)
            )
    quality = upgrade.get("quality")
    if quality not in QUALITY_TIERS:
        issues.append(
            _issue("quality_invalid", f"quality must be one of {list(QUALITY_TIERS)}", quality=quality)
        )
    if upgrade.get("recording_never_downgrades") is not True:
        issues.append(
            _issue("recording_downgrade_allowed",
                   "upgrade must declare recording_never_downgrades=true: quality must "
                   "never drop while recording, or frame hashes cannot stay identical")
        )

    post = upgrade.get("post")
    if not isinstance(post, dict):
        issues.append(_issue("post_missing", "upgrade must carry a 'post' object"))
        post = {}
    bloom = post.get("bloom")
    if not isinstance(bloom, dict):
        issues.append(_issue("bloom_missing", "post must carry a 'bloom' object"))
        bloom = {}
    for field in ("strength", "radius", "threshold"):
        if not _is_num(bloom.get(field)):
            issues.append(
                _issue("bloom_value_missing",
                       f"bloom must supply numeric {field!r} from the caller; no default is used",
                       field=field)
            )
    gtao = post.get("gtao")
    if not isinstance(gtao, dict):
        issues.append(_issue("gtao_missing", "post must carry a 'gtao' declaration object"))
        gtao = {}
    if gtao.get("enabled") is True and not isinstance(gtao.get("params"), dict):
        issues.append(
            _issue("gtao_params_missing",
                   "gtao.enabled=true requires caller-supplied 'params'; the parameters "
                   "are recorded but GTAO is not applied (no vendored GTAO pass)")
        )

    budget = upgrade.get("budget")
    if not isinstance(budget, dict):
        issues.append(_issue("budget_missing", "upgrade must carry a caller-supplied 'budget' object"))
        budget = {}
    for field in ("max_frame_ms", "max_draw_calls", "max_triangles"):
        if not _is_num(budget.get(field)) or float(budget.get(field, 0)) <= 0:
            issues.append(
                _issue("budget_value_missing",
                       f"budget must supply positive numeric {field!r} from the caller; "
                       "no default budget is used",
                       field=field)
            )

    vantages = upgrade.get("vantages")
    if not isinstance(vantages, dict) or not vantages:
        issues.append(_issue("vantages_missing", "upgrade must carry a non-empty 'vantages' object"))
        vantages = {}
    for name, vantage in vantages.items():
        if not isinstance(vantage, dict):
            issues.append(_issue("vantage_not_object", f"vantage {name!r} must be an object", vantage=name))
            continue
        for field in ("position", "target"):
            value = vantage.get(field)
            if not (isinstance(value, list) and len(value) == 3 and all(_is_num(v) for v in value)):
                issues.append(
                    _issue("vantage_vector_invalid",
                           f"vantage {name!r} {field!r} must be [x, y, z] numbers",
                           vantage=name, field=field)
                )
        fov = vantage.get("fov")
        if not _is_num(fov) or not 1.0 <= float(fov) <= 120.0:
            issues.append(
                _issue("vantage_fov_invalid", f"vantage {name!r} fov must be in [1, 120]",
                       vantage=name)
            )
    flights = upgrade.get("flights", [])
    if not isinstance(flights, list):
        issues.append(_issue("flights_not_list", "flights must be a list"))
        flights = []
    for index, flight in enumerate(flights):
        if not isinstance(flight, dict):
            issues.append(_issue("flight_not_object", f"flight {index} must be an object", index=index))
            continue
        for field in ("from_vantage", "to_vantage"):
            if flight.get(field) not in vantages:
                issues.append(
                    _issue("flight_vantage_unknown",
                           f"flight {index} {field}={flight.get(field)!r} is not a declared vantage",
                           index=index, field=field)
                )
        if not _is_num(flight.get("duration_s")) or float(flight.get("duration_s", 0)) <= 0:
            issues.append(
                _issue("flight_duration_invalid", f"flight {index} duration_s must be a positive number",
                       index=index)
            )
        if not _is_num(flight.get("arc_height")):
            issues.append(
                _issue("flight_arc_missing", f"flight {index} arc_height must be supplied as a number",
                       index=index)
            )

    adapter = check_adapter_plan({"adapter": plan.get("adapter")}) if isinstance(plan.get("adapter"), dict) else None
    render = check_render_plan(plan.get("render")) if isinstance(plan.get("render"), dict) else None
    if adapter is not None:
        issues.extend(adapter["issues"])
    if render is not None:
        issues.extend(render["issues"])
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "issues": issues, "upgrade": upgrade}


def build_upgrade_plan(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    seed: int = 0,
    quality: str,
    presets: dict[str, Any],
    quality_params: dict[str, Any],
    post: dict[str, Any],
    budget: dict[str, Any],
    vantages: dict[str, Any],
    flights: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "adapter": {
            "protocol": "__hf",
            "methods": ["getDurationFrames", "seekFrame", "destroy"],
            "settle": {"mode": "confirmation", "max_wait_ms": 5000},
            "arbitrary_order": True,
        },
        "render": {
            "fps": fps,
            "width": width,
            "height": height,
            "locked_before_frame_0": True,
            "wall_clock_sources": [],
            "randomness": {"seeded": True, "seed": seed},
            "fetch_during_render": False,
            "atomic_capture": True,
            "encoder": {"chunk_order": "sequential", "hash_check": True},
        },
        "upgrade": {
            "presets": presets,
            "quality": quality,
            "quality_params": quality_params,
            "recording_never_downgrades": True,
            "post": post,
            "budget": budget,
            "vantages": vantages,
            "flights": flights,
            "duration_s": duration_s,
        },
    }


def build_upgrade_html(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    presets: dict[str, Any],
    quality: str,
    quality_params: dict[str, Any],
    post: dict[str, Any],
    vantages: dict[str, Any],
    flights: list[dict[str, Any]],
    seed: int = 0,
) -> str:
    total = max(1, round(duration_s * fps))
    tier = quality_params[quality]
    c = HEIGHT_CONSTANTS
    js = f"""
import * as THREE from 'three';
import {{ EffectComposer }} from '/postprocessing/EffectComposer.js';
import {{ RenderPass }} from '/postprocessing/RenderPass.js';
import {{ UnrealBloomPass }} from '/postprocessing/UnrealBloomPass.js';
import {{ OutputPass }} from '/postprocessing/OutputPass.js';
const W = {width}, H = {height}, FPS = {fps}, TOTAL = {total}, DUR = {duration_s!r};
const PRESETS = {json.dumps(presets)};
const TIER = {json.dumps(tier)};
const VANTAGES = {json.dumps(vantages)};
const FLIGHTS = {json.dumps(flights)};
const SEED = {seed};
const HC = {json.dumps(c)};
function fnv(label) {{ let h = 2166136261; for (let i = 0; i < label.length; i++) {{ h ^= label.charCodeAt(i); h = Math.imul(h, 16777619); }} return h >>> 0; }}
function mulberry32(seed) {{ let s = seed >>> 0; return function () {{ s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }}; }}
function heightAt(x, z) {{
  const plateau = HC.plateau_height / (1.0 + Math.exp((x - HC.plateau_edge_x) / HC.plateau_softness));
  const hills = HC.hill_amp1 * Math.sin(x * 0.09 + 0.7) * Math.cos(z * 0.07 + 0.3)
    + HC.hill_amp2 * Math.sin(x * 0.23) * Math.sin(z * 0.19 + 1.3);
  const dx = x - HC.mound_x, dz = z - HC.mound_z;
  const mound = HC.mound_amp * Math.exp(-(dx * dx + dz * dz) / HC.mound_sigma2);
  return HC.base + plateau + hills + mound;
}}
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, TIER.pixel_ratio_cap));
renderer.setSize(W, H, false);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 900);
let presetName = 'morning';
let vantageName = Object.keys(VANTAGES)[0];
let flightName = null;
function applyPreset(name) {{
  const p = PRESETS[name];
  presetName = name;
  renderer.toneMappingExposure = p.exposure;
  scene.fog = new THREE.FogExp2(new THREE.Color(p.fog_color), p.fog_density);
  skyUniforms.uHorizon.value.set(p.sky_horizon);
  skyUniforms.uZenith.value.set(p.sky_zenith);
  skyUniforms.uSunColor.value.set(p.sun_color);
  const el = p.sun_elevation_deg * Math.PI / 180, az = p.sun_azimuth_deg * Math.PI / 180;
  sunDir.set(Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az));
  skyUniforms.uSunDir.value.copy(sunDir);
  sun.color.set(p.sun_color);
  sun.intensity = p.sun_intensity;
  sun.position.copy(sunDir).multiplyScalar(120);
  hemi.color.set(p.hemisphere_sky);
  hemi.groundColor.set(p.hemisphere_ground);
  hemi.intensity = p.hemisphere_intensity;
  window.__upgradeSettled = name;
}}
const sunDir = new THREE.Vector3(0, 1, 0);
const skyUniforms = {{
  uSunDir: {{ value: sunDir.clone() }},
  uHorizon: {{ value: new THREE.Color(0xd8c9a8) }},
  uZenith: {{ value: new THREE.Color(0x6fa3d8) }},
  uSunColor: {{ value: new THREE.Color(0xffe8c0) }}
}};
const sky = new THREE.Mesh(
  new THREE.SphereGeometry(420, 32, 16),
  new THREE.ShaderMaterial({{
    side: THREE.BackSide, depthWrite: false, fog: false, uniforms: skyUniforms,
    vertexShader: 'varying vec3 vDir; void main() {{ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }}',
    fragmentShader: 'varying vec3 vDir; uniform vec3 uSunDir; uniform vec3 uHorizon; uniform vec3 uZenith; uniform vec3 uSunColor; void main() {{ float h = clamp(vDir.y, 0.0, 1.0); vec3 col = mix(uHorizon, uZenith, pow(h, 0.55)); float s = max(dot(normalize(vDir), uSunDir), 0.0); col += uSunColor * (pow(s, 900.0) * 3.0 + pow(s, 24.0) * 0.25); gl_FragColor = vec4(col, 1.0); }}'
  }})
);
scene.add(sky);
const sun = new THREE.DirectionalLight(0xffe8c0, 2.2);
sun.castShadow = true;
sun.shadow.mapSize.set(TIER.shadow_map_size, TIER.shadow_map_size);
sun.shadow.camera.left = -60; sun.shadow.camera.right = 60;
sun.shadow.camera.top = 60; sun.shadow.camera.bottom = -60;
sun.shadow.camera.near = 10; sun.shadow.camera.far = 260;
sun.shadow.bias = -0.0005;
scene.add(sun);
scene.add(sun.target);
const hemi = new THREE.HemisphereLight(0x6fa3d8, 0x8a7a5a, 0.55);
scene.add(hemi);
scene.add(new THREE.AmbientLight(0xffffff, 0.12));
const SIZE = 140, SEG = TIER.terrain_segments;
const geo = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG);
geo.rotateX(-Math.PI / 2);
const pos = geo.attributes.position;
const colors = new Float32Array(pos.count * 3);
const sand = new THREE.Color(0xc2a878), grass = new THREE.Color(0x5d7a3a), rock = new THREE.Color(0x8d8578), high = new THREE.Color(0xb8b0a0);
const tmp = new THREE.Color();
for (let i = 0; i < pos.count; i++) {{
  const x = pos.getX(i), z = pos.getZ(i);
  const h = heightAt(x, z);
  pos.setY(i, h);
  if (h < 2.2) tmp.copy(sand); else if (h < 6.0) tmp.copy(grass); else if (h < 9.5) tmp.copy(rock); else tmp.copy(high);
  colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b;
}}
geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
geo.computeVertexNormals();
const terrain = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({{ vertexColors: true, roughness: 0.95, metalness: 0.0 }}));
terrain.receiveShadow = true;
scene.add(terrain);
const water = new THREE.Mesh(
  new THREE.PlaneGeometry(70, 70),
  new THREE.MeshStandardMaterial({{ color: 0x3f7fa8, roughness: 0.15, metalness: 0.0, transparent: true, opacity: 0.78 }})
);
water.rotation.x = -Math.PI / 2;
water.position.set(28, 1.6, 0);
scene.add(water);
function scatter(label, count, mesh, yOff) {{
  const rand = mulberry32(fnv(label) ^ (SEED === 0 ? 12345 : SEED));
  const dummy = new THREE.Object3D();
  for (let i = 0; i < count; i++) {{
    const x = -60 + rand() * 120, z = -60 + rand() * 120;
    const s = 0.5 + rand() * 1.1;
    dummy.position.set(x, heightAt(x, z) + yOff * s, z);
    dummy.rotation.set(0, rand() * Math.PI * 2, 0);
    dummy.scale.setScalar(s);
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
  }}
  mesh.instanceMatrix.needsUpdate = true;
}}
const rocks = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.55, 0), new THREE.MeshStandardMaterial({{ color: 0x7d766a, roughness: 0.9 }}), 40);
rocks.castShadow = true;
scatter('rocks', 40, rocks, 0.1);
scene.add(rocks);
const trees = new THREE.InstancedMesh(new THREE.ConeGeometry(1.1, 4.2, 8), new THREE.MeshStandardMaterial({{ color: 0x2f5230, roughness: 0.85 }}), 24);
trees.castShadow = true;
scatter('trees', 24, trees, 2.0);
scene.add(trees);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(new THREE.Vector2(W, H), {json.dumps(post["bloom"]["strength"])}, {json.dumps(post["bloom"]["radius"])}, {json.dumps(post["bloom"]["threshold"])});
composer.addPass(bloomPass);
composer.addPass(new OutputPass());
let lastStats = {{ calls: 0, triangles: 0 }};
function renderSceneForStats() {{
  renderer.render(scene, camera);
  lastStats = {{ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles }};
}}
function update(t) {{
  water.position.y = 1.6 + 0.05 * Math.sin(t * 1.3);
  if (flightName) {{
    const flight = FLIGHTS.find(function (f) {{ return f.name === flightName; }});
    const from = VANTAGES[flight.from_vantage], to = VANTAGES[flight.to_vantage];
    const k = flight.duration_s > 0 ? Math.min(1, Math.max(0, t / flight.duration_s)) : 0;
    const arc = Math.sin(Math.PI * k) * flight.arc_height;
    camera.position.set(
      from.position[0] + (to.position[0] - from.position[0]) * k,
      from.position[1] + (to.position[1] - from.position[1]) * k + arc,
      from.position[2] + (to.position[2] - from.position[2]) * k
    );
    camera.lookAt(
      from.target[0] + (to.target[0] - from.target[0]) * k,
      from.target[1] + (to.target[1] - from.target[1]) * k,
      from.target[2] + (to.target[2] - from.target[2]) * k
    );
  }} else {{
    const v = VANTAGES[vantageName];
    camera.position.set(v.position[0], v.position[1], v.position[2]);
    camera.lookAt(v.target[0], v.target[1], v.target[2]);
  }}
  camera.fov = VANTAGES[vantageName].fov;
  camera.updateProjectionMatrix();
  sky.position.copy(camera.position);
  sun.target.position.set(camera.position.x, 0, camera.position.z);
}}
window.__upgradeStats = function () {{
  return {{ calls: lastStats.calls, triangles: lastStats.triangles,
    preset: presetName, quality: '{quality}', quality_locked: true,
    applied_stack: ['RenderPass', 'UnrealBloomPass', 'OutputPass'],
    gtao_applied: false,
    gtao_reason: 'no vendored GTAO pass in this repository; nothing downloaded' }};
}};
window.__upgrade = {{
  setPreset(name) {{ applyPreset(name); update(0); renderSceneForStats(); composer.render(); }},
  setVantage(name) {{ vantageName = name; flightName = null; }},
  setFlight(name) {{ flightName = name; }},
  stats() {{ return window.__upgradeStats(); }}
}};
window.__hfSettledFrame = -1;
window.__upgradeSettled = '';
window.__hf = {{
  getDurationFrames() {{ return TOTAL; }},
  seekFrame(frame) {{
    if (!Number.isInteger(frame) || frame < 0 || frame >= TOTAL) throw new RangeError('frame out of range: ' + frame);
    const t = Math.floor(frame) / FPS;
    update(t);
    renderSceneForStats();
    composer.render();
    window.__hfSettledFrame = frame;
    return {{ frame: frame, t: t, settled: true }};
  }},
  destroy() {{ renderer.dispose(); }}
}};
applyPreset(presetName);
update(0);
renderSceneForStats();
composer.render();
window.__hfReady = true;
"""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">\n"
        "<style>html,body{margin:0;padding:0;background:#0b0b12;overflow:hidden}"
        "canvas{display:block}</style>\n"
        "<script>window.__hfError=null;window.__hfReady=false;"
        "window.__hfSettledFrame=-1;window.__upgradeSettled='';"
        "window.addEventListener('error',function(e){"
        "window.__hfError=String((e&&e.message)||'page error');});</script>\n"
        "<script type=\"importmap\">{\"imports\":{\"three\":\"/three.module.js\"}}</script>\n"
        f"</head><body><div id=\"stage\"></div>\n<script type=\"module\">{js}</script>\n</body></html>"
    )


class _VendorHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        vendor_root: Path = self.server.vendor_root  # type: ignore[attr-defined]
        if self.path == "/":
            body, ctype = self.server.html_bytes, "text/html; charset=utf-8"  # type: ignore[attr-defined]
        else:
            rel = self.path.lstrip("/").split("?", 1)[0]
            candidate = (vendor_root / rel).resolve()
            if not str(candidate).startswith(str(vendor_root.resolve())) or not candidate.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body, ctype = candidate.read_bytes(), "text/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def render_upgrade(
    *,
    presets: dict[str, Any],
    quality: str,
    quality_params: dict[str, Any],
    post: dict[str, Any],
    budget: dict[str, Any],
    vantages: dict[str, Any],
    flights: list[dict[str, Any]],
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    fps: int = 10,
    duration_s: float = 1.0,
    seed: int = 0,
    vantage: str | None = None,
    runs: int = 2,
) -> dict[str, Any]:
    """Render preset + flight shots ``runs`` times; hashes must match."""
    if runs < 1:
        raise CapabilityError("world.threejs_imaging_upgrade: runs must be >= 1")
    plan = build_upgrade_plan(
        width=width, height=height, fps=fps, duration_s=duration_s,
        seed=seed, quality=quality, presets=presets,
        quality_params=quality_params, post=post, budget=budget,
        vantages=vantages, flights=flights,
    )
    gate = validate_upgrade_plan(plan)
    if gate["verdict"] != "pass":
        raise CapabilityError(
            "world.threejs_imaging_upgrade: plan failed gates: "
            + "; ".join(i["message"] for i in gate["issues"])
        )
    if vantage is None:
        vantage = next(iter(vantages))
    if vantage not in vantages:
        raise CapabilityError(
            f"world.threejs_imaging_upgrade: unknown vantage {vantage!r}"
        )
    html = build_upgrade_html(
        width=width, height=height, fps=fps, duration_s=duration_s,
        presets=presets, quality=quality, quality_params=quality_params,
        post=post, vantages=vantages, flights=flights, seed=seed,
    )
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise CapabilityError(
            f"world.threejs_imaging_upgrade: Playwright is required: {exc}"
        ) from exc
    three_path = resolve_three_module()
    vendor_root = three_path.parent
    server = ThreadingHTTPServer(("127.0.0.1", 0), _VendorHandler)
    server.html_bytes = html.encode("utf-8")  # type: ignore[attr-defined]
    server.vendor_root = vendor_root  # type: ignore[attr-defined]
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            for run_index in range(runs):
                browser = pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                try:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                    )
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=30000)
                    page.wait_for_function("window.__hfReady === true", timeout=30000)
                    error = page.evaluate("window.__hfError")
                    if error:
                        raise CapabilityError(
                            f"world.threejs_imaging_upgrade: page failed to load: {error}"
                        )
                    run_dir = out_dir / f"run_{run_index}"
                    run_dir.mkdir(parents=True, exist_ok=True)
                    shots: list[dict[str, Any]] = []

                    def _shoot(name: str) -> None:
                        started = time.perf_counter()
                        shot = page.screenshot()
                        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
                        if not shot.startswith(b"\x89PNG"):
                            raise CapabilityError(
                                "world.threejs_imaging_upgrade: capture did not return a PNG"
                            )
                        path = run_dir / f"{name}.png"
                        path.write_bytes(shot)
                        stats = page.evaluate("window.__upgradeStats()")
                        shots.append({
                            "name": name,
                            "sha256": hashlib.sha256(shot).hexdigest(),
                            "bytes": len(shot),
                            "file": path.name,
                            "stats": stats,
                            "seek_plus_screenshot_ms": elapsed_ms,
                            "settled": True,
                        })

                    page.evaluate(f"window.__upgrade.setVantage({json.dumps(vantage)})")
                    for preset in PRESET_NAMES:
                        page.evaluate(f"window.__upgrade.setPreset({json.dumps(preset)})")
                        page.wait_for_function(
                            f"window.__upgradeSettled === {json.dumps(preset)}", timeout=5000
                        )
                        page.evaluate("window.__hf.seekFrame(0)")
                        page.wait_for_function("window.__hfSettledFrame === 0", timeout=5000)
                        _shoot(f"preset_{preset}")
                    for flight in flights:
                        flight_name = flight.get("name") or f"{flight['from_vantage']}_to_{flight['to_vantage']}"
                        page.evaluate(f"window.__upgrade.setFlight({json.dumps(flight_name)})")
                        frames = max(1, round(float(flight["duration_s"]) * fps))
                        for frame in range(frames):
                            page.evaluate(f"window.__hf.seekFrame({frame})")
                            page.wait_for_function(
                                f"window.__hfSettledFrame === {frame}", timeout=5000
                            )
                            _shoot(f"flight_{flight_name}_{frame:04d}")
                    all_runs.append({"run": run_index, "shots": shots})
                finally:
                    browser.close()
    finally:
        server.shutdown()
        server.server_close()
    hashes = [[s["sha256"] for s in r["shots"]] for r in all_runs]
    identical = all(h == hashes[0] for h in hashes) if hashes else True
    issues: list[dict[str, Any]] = []
    if not identical:
        issues.append({
            "code": "shot_hash_mismatch",
            "message": "two renders of the same upgrade differ; not deterministic on this machine",
        })
    budget_checks: list[dict[str, Any]] = []
    for shot in (all_runs[0]["shots"] if all_runs else []):
        stats = shot["stats"]
        calls_ok = stats["calls"] <= float(budget["max_draw_calls"])
        tris_ok = stats["triangles"] <= float(budget["max_triangles"])
        budget_checks.append({
            "shot": shot["name"],
            "draw_calls": stats["calls"],
            "draw_calls_within_budget": calls_ok,
            "triangles": stats["triangles"],
            "triangles_within_budget": tris_ok,
            "frame_ms": "not_checked",
            "frame_ms_reason": (
                "pure frame time is not measured by a screenshot path; "
                "seek_plus_screenshot_ms is recorded separately and is "
                "not compared with max_frame_ms"
            ),
        })
        if not calls_ok:
            issues.append({
                "code": "budget_draw_calls_exceeded",
                "message": f"shot {shot['name']} draw calls {stats['calls']} exceed budget {budget['max_draw_calls']}",
                "shot": shot["name"],
            })
        if not tris_ok:
            issues.append({
                "code": "budget_triangles_exceeded",
                "message": f"shot {shot['name']} triangles {stats['triangles']} exceed budget {budget['max_triangles']}",
                "shot": shot["name"],
            })
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "plan_gates": gate,
        "width": width, "height": height, "fps": fps,
        "duration_s": float(duration_s), "quality": quality, "seed": seed,
        "vantage": vantage,
        "three_module": str(three_path),
        "three_revision": three_revision(three_path),
        "runs": all_runs,
        "hashes_identical": identical,
        "budget_checks": budget_checks,
        "post_stack_applied": ["RenderPass", "UnrealBloomPass", "OutputPass"],
        "gtao_applied": False,
        "gtao_reason": "no vendored GTAO pass in this repository; nothing downloaded",
        "quality_locked_during_recording": True,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for field in ("presets", "quality", "quality_params", "post", "budget", "vantages"):
        if field not in params:
            raise CapabilityError(
                f"world.threejs_imaging_upgrade: missing required param {field!r} "
                "(all imaging values are caller-supplied; there are no defaults)"
            )
    report = render_upgrade(
        presets=params["presets"],
        quality=str(params["quality"]),
        quality_params=params["quality_params"],
        post=params["post"],
        budget=params["budget"],
        vantages=params["vantages"],
        flights=params.get("flights", []),
        out_dir=out_dir,
        width=int(params.get("width", 480)),
        height=int(params.get("height", 270)),
        fps=int(params.get("fps", 10)),
        duration_s=float(params.get("duration_s", duration or 1.0)),
        seed=int(params.get("seed", seed)),
        vantage=params.get("vantage"),
        runs=int(params.get("runs", 2)),
    )
    report_path = out_dir / "threejs_imaging_upgrade_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    first = out_dir / "run_0" / "preset_morning.png"
    ok = report["verdict"] == "pass"
    return CapabilityResult(
        png=str(first) if first.is_file() else None,
        duration_s=float(report.get("duration_s", 0.0)),
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"], "ok": ok,
            "hashes_identical": report.get("hashes_identical"),
            "gtao_applied": False},
    )


def register_threejs_imaging_upgrade_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="world.threejs_imaging_upgrade",
            kind="video",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "presets": {"type": "object"},
                    "quality": {"type": "string"},
                    "quality_params": {"type": "object"},
                    "post": {"type": "object"},
                    "budget": {"type": "object"},
                    "vantages": {"type": "object"},
                    "flights": {"type": "array"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "fps": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "seed": {"type": "integer"},
                    "vantage": {"type": "string"},
                    "runs": {"type": "integer"},
                },
                "required": ["presets", "quality", "quality_params", "post", "budget", "vantages"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render,
            has_media_output=True,
            description=(
                "Three.js imaging upgrade (open-3d-skills threejs-scene "
                "discipline, clean-room): three linked lighting presets, "
                "RenderPass -> UnrealBloomPass -> OutputPass over the "
                "vendored three.js r169 (GTAO declared but not applied: "
                "no vendored GTAO pass exists), a caller-supplied "
                "performance budget, three quality tiers that never "
                "downgrade while recording, named vantages and arc "
                "flights, over the athenaion heightfield. All imaging "
                "values are caller-supplied. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="world",
        )
    )
    return ["world.threejs_imaging_upgrade"]


register_threejs_imaging_upgrade_capabilities_once()
